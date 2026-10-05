from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime, time
    from decimal import Decimal

    from retail_sim.domain.enums import LocationType, OperationType, OptimizationFlag, RunStatus


@dataclass(frozen=True, slots=True)
class StorageLocation:
    id: int
    location_type: LocationType


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    category_l1: str
    category_l2: str
    name: str
    purchase_price: Decimal
    retail_price: Decimal
    avg_daily_sales: Decimal


@dataclass(frozen=True, slots=True)
class Warehouse:
    id: int
    storage_location_id: int
    name: str


@dataclass(frozen=True, slots=True)
class Store:
    id: int
    storage_location_id: int
    warehouse_id: int
    name: str
    avg_receipts_per_day: Decimal
    sku_capacity: int
    open_from: time
    open_to: time
    optimization_flag: OptimizationFlag


@dataclass(frozen=True, slots=True)
class CalculationParameters:
    id: int
    avg_receipts_per_day: int
    avg_receipt_amount: Decimal
    avg_sku_capacity: int
    min_receipt_amount: Decimal
    max_receipt_amount: Decimal
    target_stock_days_warehouse: int
    target_stock_days_store: int


@dataclass(frozen=True, slots=True)
class StoreAssortmentItem:
    store_id: int
    product_id: int
    avg_daily_sales: Decimal


@dataclass(frozen=True, slots=True)
class OpeningStock:
    stock_date: date
    storage_location_id: int
    product_id: int
    quantity: int


@dataclass(frozen=True, slots=True)
class InventoryMovement:
    id: int
    op_ts: datetime
    op_date: date
    product_id: int
    storage_location_id: int
    sender_location_id: int | None
    receiver_location_id: int | None
    quantity: int
    op_type: OperationType


@dataclass(frozen=True, slots=True)
class Receipt:
    id: int
    store_id: int
    receipt_ts: datetime


@dataclass(frozen=True, slots=True)
class ReceiptLine:
    receipt_id: int
    product_id: int
    quantity: int
    sale_price: Decimal
    discount_pct: Decimal
    clearance_flag: int


@dataclass(frozen=True, slots=True)
class SimulationRun:
    id: int
    date_from: date
    date_to: date
    days_total: int
    days_done: int
    last_done_date: date | None
    status: RunStatus
    seed: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
