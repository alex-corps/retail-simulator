from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from retail_sim.core.demand import USAGE_WINDOW_DAYS, average_usage, order_quantity
from retail_sim.domain.calendar import is_supplier_day
from retail_sim.domain.enums import OperationType
from retail_sim.repositories.locations import list_warehouses
from retail_sim.repositories.movements import (
    MovementDraft,
    daily_outflow,
    delete_receipts,
    has_any_movements,
    insert_movements,
)
from retail_sim.repositories.params import get_calculation_parameters
from retail_sim.repositories.products import list_products
from retail_sim.repositories.stock import positive_stock_days

if TYPE_CHECKING:
    from datetime import date

    from psycopg import Connection

    from retail_sim.core.stock import DayStock
    from retail_sim.domain.models import Product, Warehouse

# Первичное наполнение пустого склада: по спецификации 1000 шт на каждый SKU.
COLD_START_QUANTITY = 1000


@dataclass(frozen=True, slots=True)
class SupplierResult:
    cold_start: bool
    warehouses_supplied: int
    skus_received: int
    units_received: int


def run_supplier(conn: Connection[Any], day: date, stock: DayStock) -> SupplierResult:
    warehouses = sorted(list_warehouses(conn), key=lambda warehouse: warehouse.id)
    if not warehouses:
        return SupplierResult(False, 0, 0, 0)

    # Повторный запуск за тот же день заменяет уже записанный приход.
    location_ids = [warehouse.storage_location_id for warehouse in warehouses]
    removed = delete_receipts(conn, day, location_ids)
    for key, quantity in removed.items():
        stock.apply(key, -quantity)

    products = sorted(list_products(conn), key=lambda product: product.id)
    # После удаления прихода дня пустая история — это холодный старт, день недели не важен.
    if not has_any_movements(conn):
        drafts = _cold_start_drafts(day, warehouses, products)
        cold_start = True
    elif is_supplier_day(day):
        drafts = _replenish_drafts(conn, day, stock, warehouses, products, location_ids)
        cold_start = False
    else:
        drafts = []
        cold_start = False

    insert_movements(conn, drafts)
    for draft in drafts:
        stock.apply((draft.storage_location_id, draft.product_id), draft.quantity)
    return SupplierResult(
        cold_start=cold_start,
        warehouses_supplied=len({draft.storage_location_id for draft in drafts}),
        skus_received=len(drafts),
        units_received=sum(draft.quantity for draft in drafts),
    )


def _cold_start_drafts(
    day: date,
    warehouses: list[Warehouse],
    products: list[Product],
) -> list[MovementDraft]:
    return [
        _receipt_draft(day, warehouse.storage_location_id, product.id, COLD_START_QUANTITY)
        for warehouse in warehouses
        for product in products
    ]


def _replenish_drafts(
    conn: Connection[Any],
    day: date,
    stock: DayStock,
    warehouses: list[Warehouse],
    products: list[Product],
    location_ids: list[int],
) -> list[MovementDraft]:
    params = get_calculation_parameters(conn)
    window_to = day - timedelta(days=1)
    window_from = day - timedelta(days=USAGE_WINDOW_DAYS)
    outflow = daily_outflow(
        conn,
        location_ids,
        OperationType.TRANSFER,
        window_from,
        window_to,
    )
    in_stock = positive_stock_days(conn, location_ids, window_from, window_to)
    drafts: list[MovementDraft] = []
    for warehouse in warehouses:
        location_id = warehouse.storage_location_id
        for product in products:
            key = (location_id, product.id)
            # SKU без дней расхода и остатка получает среднюю 0 и в поставку не попадает.
            avg = average_usage(outflow.get(key, {}), in_stock.get(key, set()))
            quantity = order_quantity(avg, stock.current(key), params.target_stock_days_warehouse)
            if quantity > 0:
                drafts.append(_receipt_draft(day, location_id, product.id, quantity))
    return drafts


def _receipt_draft(day: date, location_id: int, product_id: int, quantity: int) -> MovementDraft:
    # Поставщик не является местом хранения, поэтому отправитель пустой.
    return MovementDraft(
        op_ts=datetime.combine(day, time.min),
        product_id=product_id,
        storage_location_id=location_id,
        sender_location_id=None,
        receiver_location_id=location_id,
        quantity=quantity,
        op_type=OperationType.RECEIPT,
    )
