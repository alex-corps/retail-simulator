from __future__ import annotations

from datetime import time
from decimal import Decimal
from typing import Any

import pytest
from psycopg import Connection

from retail_sim.domain.enums import LocationType, OptimizationFlag
from retail_sim.domain.models import (
    CalculationParameters,
    Product,
    StorageLocation,
    Store,
    StoreAssortmentItem,
    Warehouse,
)
from retail_sim.repositories.locations import (
    get_warehouse,
    list_storage_locations,
    list_warehouses,
)
from retail_sim.repositories.params import (
    CalculationParametersMissingError,
    get_calculation_parameters,
)
from retail_sim.repositories.products import get_product, list_products
from retail_sim.repositories.stores import (
    get_store,
    list_store_assortment,
    list_stores,
    list_stores_by_flag,
    list_unused_store_names,
)
from tests.conftest import is_db_reachable
from tests.integration.helpers import (
    insert_calculation_parameters,
    insert_product,
    insert_storage_location,
    insert_store,
    insert_warehouse,
)

pytestmark = pytest.mark.skipif(
    not is_db_reachable(),
    reason="PostgreSQL is not reachable",
)


def test_product_repository_reads_rows(db_conn: Connection[Any]) -> None:
    assert get_product(db_conn, 999_999_999) is None

    milk_id = insert_product(db_conn, name="Молоко 1л", category_l2="Молоко")
    bread_id = insert_product(
        db_conn,
        name="Хлеб",
        category_l1="Продукты",
        category_l2="Хлеб",
        purchase_price=Decimal("20.00"),
        retail_price=Decimal("35.00"),
        avg_daily_sales=Decimal("10.00"),
    )

    assert get_product(db_conn, milk_id) == Product(
        id=milk_id,
        category_l1="Продукты",
        category_l2="Молоко",
        name="Молоко 1л",
        purchase_price=Decimal("40.00"),
        retail_price=Decimal("59.90"),
        avg_daily_sales=Decimal("3.50"),
    )
    assert list_products(db_conn) == [
        Product(
            id=milk_id,
            category_l1="Продукты",
            category_l2="Молоко",
            name="Молоко 1л",
            purchase_price=Decimal("40.00"),
            retail_price=Decimal("59.90"),
            avg_daily_sales=Decimal("3.50"),
        ),
        Product(
            id=bread_id,
            category_l1="Продукты",
            category_l2="Хлеб",
            name="Хлеб",
            purchase_price=Decimal("20.00"),
            retail_price=Decimal("35.00"),
            avg_daily_sales=Decimal("10.00"),
        ),
    ]


def test_location_repository_filters_and_reads_warehouses(db_conn: Connection[Any]) -> None:
    warehouse_location_id = insert_storage_location(db_conn, "склад")
    store_location_id = insert_storage_location(db_conn, "магазин")
    warehouse_id = insert_warehouse(db_conn, warehouse_location_id, "Central")

    assert list_storage_locations(db_conn) == [
        StorageLocation(id=warehouse_location_id, location_type=LocationType.WAREHOUSE),
        StorageLocation(id=store_location_id, location_type=LocationType.STORE),
    ]
    assert list_storage_locations(db_conn, LocationType.STORE) == [
        StorageLocation(id=store_location_id, location_type=LocationType.STORE),
    ]
    assert get_warehouse(db_conn, 999_999_999) is None
    assert get_warehouse(db_conn, warehouse_id) == Warehouse(
        id=warehouse_id,
        storage_location_id=warehouse_location_id,
        name="Central",
    )
    assert list_warehouses(db_conn) == [
        Warehouse(id=warehouse_id, storage_location_id=warehouse_location_id, name="Central"),
    ]


def test_store_repository_reads_flag_names_and_assortment(db_conn: Connection[Any]) -> None:
    warehouse_location_id = insert_storage_location(db_conn, "склад")
    warehouse_id = insert_warehouse(db_conn, warehouse_location_id, "Central")
    north_location_id = insert_storage_location(db_conn, "магазин")
    south_location_id = insert_storage_location(db_conn, "магазин")
    north_id = insert_store(
        db_conn,
        storage_location_id=north_location_id,
        warehouse_id=warehouse_id,
        name="North",
        avg_receipts_per_day=Decimal("120.50"),
        sku_capacity=900,
        open_from=time(9, 30),
        open_to=time(22, 0),
        optimization_flag=1,
    )
    south_id = insert_store(
        db_conn,
        storage_location_id=south_location_id,
        warehouse_id=warehouse_id,
        name="South",
        optimization_flag=0,
    )
    product_id = insert_product(db_conn, name="Сыр")
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO store_name_pool (name) VALUES (%s), (%s), (%s)",
            ("North", "South", "East"),
        )
        cur.execute(
            """
            INSERT INTO store_assortment (store_id, product_id, avg_daily_sales)
            VALUES (%s, %s, %s)
            """,
            (north_id, product_id, Decimal("4.25")),
        )

    north = Store(
        id=north_id,
        storage_location_id=north_location_id,
        warehouse_id=warehouse_id,
        name="North",
        avg_receipts_per_day=Decimal("120.50"),
        sku_capacity=900,
        open_from=time(9, 30),
        open_to=time(22, 0),
        optimization_flag=OptimizationFlag.REQUESTED,
    )
    south = Store(
        id=south_id,
        storage_location_id=south_location_id,
        warehouse_id=warehouse_id,
        name="South",
        avg_receipts_per_day=Decimal("120.00"),
        sku_capacity=800,
        open_from=time(10, 0),
        open_to=time(21, 0),
        optimization_flag=OptimizationFlag.IDLE,
    )

    assert get_store(db_conn, 999_999_999) is None
    assert get_store(db_conn, north_id) == north
    assert list_stores(db_conn) == [north, south]
    assert list_stores_by_flag(db_conn, OptimizationFlag.REQUESTED) == [north]
    assert list_unused_store_names(db_conn) == ["East"]
    assert list_store_assortment(db_conn, north_id) == [
        StoreAssortmentItem(
            store_id=north_id,
            product_id=product_id,
            avg_daily_sales=Decimal("4.25"),
        )
    ]
    assert list_store_assortment(db_conn, south_id) == []


def test_missing_calculation_parameters_raise(db_conn: Connection[Any]) -> None:
    with pytest.raises(CalculationParametersMissingError):
        get_calculation_parameters(db_conn)


def test_calculation_parameters_roundtrip(db_conn: Connection[Any]) -> None:
    insert_calculation_parameters(db_conn)
    assert get_calculation_parameters(db_conn) == CalculationParameters(
        id=1,
        avg_receipts_per_day=800,
        avg_receipt_amount=Decimal("450.50"),
        avg_sku_capacity=5000,
        min_receipt_amount=Decimal("50.00"),
        max_receipt_amount=Decimal("15000.00"),
        target_stock_days_warehouse=14,
        target_stock_days_store=7,
    )
