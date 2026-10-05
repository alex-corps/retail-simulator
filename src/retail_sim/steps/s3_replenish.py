from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from retail_sim.core.allocation import allocate
from retail_sim.core.demand import USAGE_WINDOW_DAYS, average_usage, replenish_quantity
from retail_sim.domain.calendar import is_replenish_day
from retail_sim.domain.enums import OperationType
from retail_sim.repositories.locations import list_warehouses
from retail_sim.repositories.movements import (
    MovementDraft,
    daily_outflow,
    delete_store_replenishments,
    insert_movements,
)
from retail_sim.repositories.params import get_calculation_parameters
from retail_sim.repositories.stock import positive_stock_days
from retail_sim.repositories.stores import list_assortment_by_store, list_stores
from retail_sim.steps.s2_assortment import WarehouseMissingError

if TYPE_CHECKING:
    from datetime import date

    from psycopg import Connection

    from retail_sim.core.stock import DayStock


@dataclass(frozen=True, slots=True)
class ReplenishResult:
    stores_supplied: int
    skus_shipped: int
    units_shipped: int
    skus_short: int


def rollback_replenish(conn: Connection[Any], day: date, stock: DayStock) -> int:
    # Повторный день сначала снимает отгрузку. Возврат выведенного ассортимента остаётся.
    location_ids = [warehouse.storage_location_id for warehouse in list_warehouses(conn)]
    removed = delete_store_replenishments(conn, day, location_ids)
    for key, quantity in removed.items():
        stock.apply(key, -quantity)
    return len(removed)


def run_replenish(conn: Connection[Any], day: date, stock: DayStock) -> ReplenishResult:
    rollback_replenish(conn, day, stock)
    if not is_replenish_day(day):
        return ReplenishResult(0, 0, 0, 0)

    params = get_calculation_parameters(conn)
    warehouses = {warehouse.id: warehouse for warehouse in list_warehouses(conn)}
    stores = list_stores(conn)
    assortment = list_assortment_by_store(conn)
    store_location_ids = [store.storage_location_id for store in stores]
    window_to = day - timedelta(days=1)
    window_from = day - timedelta(days=USAGE_WINDOW_DAYS)
    # Расход магазина — продажи. День входит в среднюю, если была продажа или остаток > 0.
    sales = daily_outflow(
        conn,
        store_location_ids,
        OperationType.SALE,
        window_from,
        window_to,
    )
    in_stock = positive_stock_days(conn, store_location_ids, window_from, window_to)

    demands: dict[tuple[int, int], dict[int, int]] = {}
    locations = {store.id: (store.storage_location_id, store.warehouse_id) for store in stores}
    for store in stores:
        for item in assortment.get(store.id, []):
            key = (store.storage_location_id, item.product_id)
            avg = average_usage(sales.get(key, {}), in_stock.get(key, set()))
            quantity = replenish_quantity(
                avg,
                stock.current(key),
                params.target_stock_days_store,
                item.avg_daily_sales,
            )
            if quantity > 0:
                demands.setdefault((store.warehouse_id, item.product_id), {})[store.id] = quantity

    shipments: list[tuple[int, int, int, int, int]] = []
    skus_short = 0
    for warehouse_id, product_id in sorted(demands):
        warehouse = warehouses.get(warehouse_id)
        if warehouse is None:
            raise WarehouseMissingError(warehouse_id)
        requested = demands[(warehouse_id, product_id)]
        available = stock.current((warehouse.storage_location_id, product_id))
        if sum(requested.values()) > available:
            skus_short += 1
        granted = allocate(available, requested)
        for store_id, quantity in granted.items():
            store_location_id, _warehouse_id = locations[store_id]
            shipments.append(
                (
                    store_id,
                    product_id,
                    quantity,
                    store_location_id,
                    warehouse.storage_location_id,
                )
            )

    op_ts = datetime.combine(day, time.min)
    drafts: list[MovementDraft] = []
    for _store_id, product_id, quantity, store_location_id, warehouse_location_id in sorted(
        shipments
    ):
        drafts.extend(
            _transfer_drafts(
                op_ts,
                product_id,
                quantity,
                store_location_id,
                warehouse_location_id,
            )
        )
    insert_movements(conn, drafts)
    for draft in drafts:
        stock.apply((draft.storage_location_id, draft.product_id), draft.quantity)

    store_lines = [draft for draft in drafts if draft.quantity > 0]
    return ReplenishResult(
        stores_supplied=len({draft.storage_location_id for draft in store_lines}),
        skus_shipped=len(store_lines),
        units_shipped=sum(draft.quantity for draft in store_lines),
        skus_short=skus_short,
    )


def _transfer_drafts(
    op_ts: datetime,
    product_id: int,
    quantity: int,
    store_location_id: int,
    warehouse_location_id: int,
) -> list[MovementDraft]:
    # Пара строк: магазин получает +N, склад отдаёт -N.
    return [
        MovementDraft(
            op_ts=op_ts,
            product_id=product_id,
            storage_location_id=store_location_id,
            sender_location_id=warehouse_location_id,
            receiver_location_id=store_location_id,
            quantity=quantity,
            op_type=OperationType.TRANSFER,
        ),
        MovementDraft(
            op_ts=op_ts,
            product_id=product_id,
            storage_location_id=warehouse_location_id,
            sender_location_id=warehouse_location_id,
            receiver_location_id=store_location_id,
            quantity=-quantity,
            op_type=OperationType.TRANSFER,
        ),
    ]
