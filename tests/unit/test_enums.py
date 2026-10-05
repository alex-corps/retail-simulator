from __future__ import annotations

from retail_sim.domain.enums import LocationType, OperationType, OptimizationFlag


def test_location_type_values() -> None:
    assert LocationType.WAREHOUSE.value == "склад"
    assert LocationType.STORE.value == "магазин"
    assert {item.value for item in LocationType} == {"склад", "магазин"}


def test_operation_type_values() -> None:
    assert OperationType.RECEIPT.value == "приход"
    assert OperationType.TRANSFER.value == "перемещение"
    assert OperationType.SALE.value == "продажа"
    assert {item.value for item in OperationType} == {"приход", "перемещение", "продажа"}


def test_optimization_flag_values() -> None:
    assert OptimizationFlag.IDLE.value == 0
    assert OptimizationFlag.REQUESTED.value == 1
    assert OptimizationFlag.COMPLETED.value == 2
    assert [int(flag) for flag in OptimizationFlag] == [0, 1, 2]
