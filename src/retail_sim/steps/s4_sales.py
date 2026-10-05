from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

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
    lines: tuple[tuple[int, int], ...]


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
                prices_kop,
                avg_kop,
                min_kop,
                max_kop,
                seed,
            )
        )
    if not built:
        return SalesResult(0, 0, 0, 0, Decimal("0.00"))
    return _persist(conn, stock, built, prices)


def _store_receipts(
    day: date,
    store: Store,
    assortment: list[StoreAssortmentItem],
    stock: DayStock,
    prices_kop: dict[int, int],
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
    amounts = plan_receipt_amounts(
        plan_day_revenue(avg_kop, store.avg_receipts_per_day, rng),
        avg_kop,
        min_kop,
        max_kop,
        rng,
    )
    timestamps = receipt_timestamps(day, store.open_from, store.open_to, len(amounts), rng)
    built: list[_BuiltReceipt] = []
    for amount, receipt_ts in zip(amounts, timestamps, strict=True):
        lines = fill_receipt(amount, prices_kop, pool, rng)
        # Пустой чек значит, что магазин уже распродан: остальные чеки дня не создаём.
        if not lines:
            break
        built.append(
            _BuiltReceipt(
                store_id=store.id,
                location_id=store.storage_location_id,
                receipt_ts=receipt_ts,
                lines=tuple(sorted(lines.items())),
            )
        )
    return built


def _persist(
    conn: Connection[Any],
    stock: DayStock,
    built: list[_BuiltReceipt],
    prices: dict[int, Decimal],
) -> SalesResult:
    receipt_ids = reserve_receipt_ids(conn, len(built))
    insert_receipts(
        conn,
        [
            (receipt_id, receipt.store_id, receipt.receipt_ts)
            for receipt_id, receipt in zip(receipt_ids, built, strict=True)
        ],
    )
    line_rows: list[tuple[int, int, int, Decimal]] = []
    drafts: list[MovementDraft] = []
    for receipt_id, receipt in zip(receipt_ids, built, strict=True):
        for product_id, quantity in receipt.lines:
            line_rows.append((receipt_id, product_id, quantity, prices[product_id]))
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
            Decimal(quantity) * prices[product_id]
            for receipt in built
            for product_id, quantity in receipt.lines
        ),
        Decimal("0.00"),
    )
    return SalesResult(
        stores_with_sales=len({receipt.store_id for receipt in built}),
        receipts_created=len(built),
        lines_created=len(line_rows),
        units_sold=sum(quantity for receipt in built for _product_id, quantity in receipt.lines),
        revenue=revenue.quantize(_KOPECK, rounding=ROUND_HALF_UP),
    )


def _kopecks(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
