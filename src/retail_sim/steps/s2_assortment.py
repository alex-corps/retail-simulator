from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import TYPE_CHECKING, Any

from retail_sim.core.assortment import (
    SubKey,
    allocate_quotas,
    build_optimized_items,
    find_delisted,
    pick_best,
    pick_random,
    store_avg_sales,
)
from retail_sim.domain.enums import OperationType, OptimizationFlag
from retail_sim.repositories.locations import list_warehouses
from retail_sim.repositories.movements import MovementDraft, insert_movements
from retail_sim.repositories.products import list_products
from retail_sim.repositories.stores import (
    list_store_assortment,
    list_store_ids_with_assortment,
    list_stores,
    replace_store_assortment,
    set_optimization_flag,
)
from retail_sim.rng import make_rng

if TYPE_CHECKING:
    import random
    from datetime import date
    from decimal import Decimal

    from psycopg import Connection

    from retail_sim.core.stock import DayStock
    from retail_sim.domain.models import Product, Store, Warehouse


@dataclass(frozen=True, slots=True)
class AssortmentResult:
    stores_filled: int
    stores_optimized: int
    skus_returned: int


class WarehouseMissingError(Exception):
    def __init__(self, warehouse_id: int) -> None:
        self.warehouse_id = warehouse_id
        super().__init__(f"Warehouse {warehouse_id} does not exist")


def run_assortment(
    conn: Connection[Any],
    day: date,
    stock: DayStock,
    seed: int,
) -> AssortmentResult:
    products = list_products(conn)
    product_by_id = {product.id: product for product in products}
    groups = _group_products(products)
    sizes = {key: len(items) for key, items in groups.items()}
    ids_by_group = {key: [item.id for item in items] for key, items in groups.items()}
    priority = _sales_priority(groups)
    assortment_store_ids = set(list_store_ids_with_assortment(conn))
    warehouses = {warehouse.id: warehouse for warehouse in list_warehouses(conn)}

    filled = 0
    optimized = 0
    returned = 0
    for store in list_stores(conn):
        rng = make_rng(seed, day.isoformat(), store.id)
        if store.id not in assortment_store_ids:
            _fill_new_store(conn, store, product_by_id, ids_by_group, sizes, rng)
            filled += 1
            continue
        if store.optimization_flag != OptimizationFlag.REQUESTED:
            continue
        returned += _optimize_store(
            conn,
            day,
            stock,
            store,
            warehouses,
            product_by_id,
            groups,
            sizes,
            priority,
            rng,
        )
        optimized += 1
    return AssortmentResult(filled, optimized, returned)


def _group_products(products: list[Product]) -> dict[SubKey, list[Product]]:
    groups: dict[SubKey, list[Product]] = {}
    for product in products:
        groups.setdefault((product.category_l1, product.category_l2), []).append(product)
    return groups


def _sales_priority(
    groups: dict[SubKey, list[Product]],
) -> dict[SubKey, tuple[Decimal, ...]]:
    priority: dict[SubKey, tuple[Decimal, ...]] = {}
    for key, items in groups.items():
        ranked = sorted(items, key=lambda product: (-product.avg_daily_sales, product.id))
        priority[key] = tuple(product.avg_daily_sales for product in ranked)
    return priority


def _fill_new_store(
    conn: Connection[Any],
    store: Store,
    product_by_id: dict[int, Product],
    ids_by_group: dict[SubKey, list[int]],
    sizes: dict[SubKey, int],
    rng: random.Random,
) -> None:
    quotas = allocate_quotas(store.sku_capacity, sizes, rng)
    chosen = pick_random(ids_by_group, quotas, rng)
    items = [
        (product_id, store_avg_sales(product_by_id[product_id].avg_daily_sales, rng))
        for product_id in sorted(chosen)
    ]
    replace_store_assortment(conn, store.id, items)


def _optimize_store(
    conn: Connection[Any],
    day: date,
    stock: DayStock,
    store: Store,
    warehouses: dict[int, Warehouse],
    product_by_id: dict[int, Product],
    groups: dict[SubKey, list[Product]],
    sizes: dict[SubKey, int],
    priority: dict[SubKey, tuple[Decimal, ...]],
    rng: random.Random,
) -> int:
    warehouse = warehouses.get(store.warehouse_id)
    if warehouse is None:
        raise WarehouseMissingError(store.warehouse_id)
    quotas = allocate_quotas(store.sku_capacity, sizes, rng, priority)
    chosen = pick_best(groups, quotas)
    old_items = {
        item.product_id: item.avg_daily_sales for item in list_store_assortment(conn, store.id)
    }
    items = build_optimized_items(old_items, chosen, product_by_id, rng)
    delisted = find_delisted(old_items, chosen, store.storage_location_id, stock)
    _return_to_warehouse(conn, day, stock, store, warehouse, delisted)
    replace_store_assortment(conn, store.id, items)
    set_optimization_flag(conn, store.id, OptimizationFlag.COMPLETED)
    return len(delisted)


def _return_to_warehouse(
    conn: Connection[Any],
    day: date,
    stock: DayStock,
    store: Store,
    warehouse: Warehouse,
    delisted: dict[int, int],
) -> None:
    if not delisted:
        return
    op_ts = datetime.combine(day, time.min)
    store_location_id = store.storage_location_id
    warehouse_location_id = warehouse.storage_location_id
    drafts: list[MovementDraft] = []
    for product_id, quantity in delisted.items():
        drafts.append(
            MovementDraft(
                op_ts=op_ts,
                product_id=product_id,
                storage_location_id=store_location_id,
                sender_location_id=store_location_id,
                receiver_location_id=warehouse_location_id,
                quantity=-quantity,
                op_type=OperationType.TRANSFER,
            )
        )
        drafts.append(
            MovementDraft(
                op_ts=op_ts,
                product_id=product_id,
                storage_location_id=warehouse_location_id,
                sender_location_id=store_location_id,
                receiver_location_id=warehouse_location_id,
                quantity=quantity,
                op_type=OperationType.TRANSFER,
            )
        )
        stock.apply((store_location_id, product_id), -quantity)
        stock.apply((warehouse_location_id, product_id), quantity)
    insert_movements(conn, drafts)
