from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from retail_sim.core.promo import discount_percent, sale_price, scale_day_revenue
from retail_sim.core.receipts import (
    AvailableSkus,
    fill_receipt,
    plan_day_revenue,
    plan_receipt_amounts,
    receipt_timestamps,
)
from retail_sim.domain.enums import OperationType
from retail_sim.repositories.movements import MovementDraft, delete_sales, insert_movements
from retail_sim.repositories.params import get_calculation_parameters
from retail_sim.repositories.products import list_products
from retail_sim.repositories.promo import effective_price_factors
from retail_sim.repositories.receipts import (
    delete_day_receipts,
    insert_receipt_lines,
    insert_receipts,
    reserve_receipt_ids,
)
from retail_sim.repositories.stores import list_assortment_by_store, list_stores
from retail_sim.rng import make_rng

if TYPE_CHECKING:
    from datetime import date, datetime

    from psycopg import Connection

    from retail_sim.core.stock import DayStock
    from retail_sim.domain.models import Store, StoreAssortmentItem

_KOPECK = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class SalesResult:
    stores_with_sales: int
    receipts_created: int
    lines_created: int
    units_sold: int
    revenue: Decimal


@dataclass(frozen=True, slots=True)
class _BuiltReceipt:
    store_id: int
    location_id: int
    receipt_ts: datetime
    lines: tuple[tuple[int, int, Decimal], ...]
    discount_pct: Decimal
    clearance_flag: int


def rollback_sales(conn: Connection[Any], day: date, stock: DayStock) -> int:
    location_ids = [store.storage_location_id for store in list_stores(conn)]
    removed = delete_sales(conn, day, location_ids)
    for key, quantity in removed.items():
        stock.apply(key, -quantity)
    delete_day_receipts(conn, day)
    return len(removed)


def run_sales(conn: Connection[Any], day: date, stock: DayStock, seed: int) -> SalesResult:
    # Повторный запуск за тот же день заменяет уже записанные продажи.
    rollback_sales(conn, day, stock)
    params = get_calculation_parameters(conn)
    prices = {product.id: product.retail_price for product in list_products(conn)}
    prices_kop = {product_id: _kopecks(price) for product_id, price in prices.items()}
    assortment = list_assortment_by_store(conn)
    # Нет периода — план выручки и последовательность случайных чисел не меняются.
    factors = effective_price_factors(conn, day)
    avg_kop = _kopecks(params.avg_receipt_amount)
    min_kop = _kopecks(params.min_receipt_amount)
    max_kop = _kopecks(params.max_receipt_amount)

    built: list[_BuiltReceipt] = []
    for store in list_stores(conn):
        built.extend(
            _store_receipts(
                day,
                store,
                assortment.get(store.id, []),
                stock,
                prices,
                prices_kop,
                factors.get(store.id),
                avg_kop,
                min_kop,
                max_kop,
                seed,
            )
        )
    if not built:
        return SalesResult(0, 0, 0, 0, Decimal("0.00"))
    return _persist(conn, stock, built)


def _store_receipts(
    day: date,
    store: Store,
    assortment: list[StoreAssortmentItem],
    stock: DayStock,
    prices: dict[int, Decimal],
    prices_kop: dict[int, int],
    price_factor: Decimal | None,
    avg_kop: int,
    min_kop: int,
    max_kop: int,
    seed: int,
) -> list[_BuiltReceipt]:
    available = {
        item.product_id: stock.current((store.storage_location_id, item.product_id))
        for item in assortment
    }
    pool = AvailableSkus(available)
    if len(pool) == 0:
        return []
    rng = make_rng(seed, "sales", day.isoformat(), store.id)
    revenue = plan_day_revenue(avg_kop, store.avg_receipts_per_day, rng)
    charged = prices
    unit_prices = prices_kop
    discount_pct = Decimal("0.00")
    clearance_flag = 0
    if price_factor is not None:
        # Сниженная цена и больший план выручки вместе дают рост штук как f^(-E).
        revenue = scale_day_revenue(revenue, price_factor)
        charged = {
            product_id: sale_price(retail, price_factor) for product_id, retail in prices.items()
        }
        unit_prices = {product_id: _kopecks(price) for product_id, price in charged.items()}
        _require_positive_prices(unit_prices, available)
        discount_pct = discount_percent(price_factor)
        clearance_flag = 1
    amounts = plan_receipt_amounts(revenue, avg_kop, min_kop, max_kop, rng)
    timestamps = receipt_timestamps(day, store.open_from, store.open_to, len(amounts), rng)
    built: list[_BuiltReceipt] = []
    for amount, receipt_ts in zip(amounts, timestamps, strict=True):
        lines = fill_receipt(amount, unit_prices, pool, rng)
        # Пустой чек значит, что магазин уже распродан: остальные чеки дня не создаём.
        if not lines:
            break
        built.append(
            _BuiltReceipt(
                store_id=store.id,
                location_id=store.storage_location_id,
                receipt_ts=receipt_ts,
                lines=tuple(
                    (product_id, quantity, charged[product_id])
                    for product_id, quantity in sorted(lines.items())
                ),
                discount_pct=discount_pct,
                clearance_flag=clearance_flag,
            )
        )
    return built


def _require_positive_prices(unit_prices: dict[int, int], available: dict[int, int]) -> None:
    for product_id, quantity in available.items():
        if quantity > 0 and unit_prices[product_id] <= 0:
            raise ValueError(f"sale price for product {product_id} rounded to zero")


def _persist(
    conn: Connection[Any],
    stock: DayStock,
    built: list[_BuiltReceipt],
) -> SalesResult:
    receipt_ids = reserve_receipt_ids(conn, len(built))
    insert_receipts(
        conn,
        [
            (receipt_id, receipt.store_id, receipt.receipt_ts)
            for receipt_id, receipt in zip(receipt_ids, built, strict=True)
        ],
    )
    line_rows: list[tuple[int, int, int, Decimal, Decimal, int]] = []
    drafts: list[MovementDraft] = []
    for receipt_id, receipt in zip(receipt_ids, built, strict=True):
        for product_id, quantity, price in receipt.lines:
            line_rows.append(
                (
                    receipt_id,
                    product_id,
                    quantity,
                    price,
                    receipt.discount_pct,
                    receipt.clearance_flag,
                )
            )
            drafts.append(
                MovementDraft(
                    op_ts=receipt.receipt_ts,
                    product_id=product_id,
                    storage_location_id=receipt.location_id,
                    sender_location_id=receipt.location_id,
                    receiver_location_id=None,
                    quantity=-quantity,
                    op_type=OperationType.SALE,
                )
            )
    insert_receipt_lines(conn, line_rows)
    insert_movements(conn, drafts)
    for draft in drafts:
        stock.apply((draft.storage_location_id, draft.product_id), draft.quantity)

    revenue = sum(
        (
            Decimal(quantity) * price
            for receipt in built
            for _product_id, quantity, price in receipt.lines
        ),
        Decimal("0.00"),
    )
    return SalesResult(
        stores_with_sales=len({receipt.store_id for receipt in built}),
        receipts_created=len(built),
        lines_created=len(line_rows),
        units_sold=sum(
            quantity for receipt in built for _product_id, quantity, _price in receipt.lines
        ),
        revenue=revenue.quantize(_KOPECK, rounding=ROUND_HALF_UP),
    )


def _kopecks(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
