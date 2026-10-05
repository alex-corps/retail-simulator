from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from psycopg.rows import class_row

from retail_sim.domain.enums import LocationType
from retail_sim.domain.models import StorageLocation, Warehouse

if TYPE_CHECKING:
    from psycopg import Connection


def _as_location(row: StorageLocation) -> StorageLocation:
    return replace(row, location_type=LocationType(str(row.location_type)))


def list_storage_locations(
    conn: Connection[Any],
    location_type: LocationType | None = None,
) -> list[StorageLocation]:
    with conn.cursor(row_factory=class_row(StorageLocation)) as cur:
        cur.execute(
            """
            SELECT id, location_type
            FROM storage_locations
            WHERE (%(location_type)s::varchar IS NULL OR location_type = %(location_type)s)
            ORDER BY id
            """,
            {"location_type": None if location_type is None else str(location_type)},
        )
        rows = cur.fetchall()
    return [_as_location(row) for row in rows]


def list_warehouses(conn: Connection[Any]) -> list[Warehouse]:
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute(
            """
            SELECT id, storage_location_id, name
            FROM warehouses
            ORDER BY id
            """
        )
        return cur.fetchall()


def get_warehouse(conn: Connection[Any], warehouse_id: int) -> Warehouse | None:
    with conn.cursor(row_factory=class_row(Warehouse)) as cur:
        cur.execute(
            """
            SELECT id, storage_location_id, name
            FROM warehouses
            WHERE id = %s
            """,
            (warehouse_id,),
        )
        return cur.fetchone()
