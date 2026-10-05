from __future__ import annotations

from enum import IntEnum, StrEnum


class LocationType(StrEnum):
    WAREHOUSE = "склад"
    STORE = "магазин"


class OperationType(StrEnum):
    RECEIPT = "приход"
    TRANSFER = "перемещение"
    SALE = "продажа"


class OptimizationFlag(IntEnum):
    IDLE = 0
    REQUESTED = 1
    COMPLETED = 2


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
