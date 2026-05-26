"""
core/delivery_logger.py

Flight-leg logging to Trino/Iceberg.

In v1 this module connected directly to a live Trino cluster.  In v2 the
primary event log is the local SQLite delivery_events table (see core/events.py
and core/setup_db.py).  This module is preserved for the eventual cloud sync
layer but is intentionally non-functional until a Trino connection is
configured — it will print a warning and return without writing rather than
crashing the simulation.

When Trino is available the TRINO_CONFIG dict below should be populated
(via environment variables or a config file) and the guard at the top of
insert_delivery_leg() can be removed.

Legacy notes:
  - The original file imported `from config.trino_config import TRINO_CONFIG`
    (a relative sys-path hack that no longer resolves).  Trino config is now
    expected via the trino_config kwarg or the module-level TRINO_CONFIG dict.
  - The delivery_logs Iceberg table schema is preserved in
    legacy/terrain_v1/create_iceberg_delivery_table.py.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Trino connection config
#
# Populate from environment variables in production.  Leave empty to run the
# simulation in local-only mode where events go to SQLite only.
# ---------------------------------------------------------------------------
TRINO_CONFIG: dict = {
    # "host":     os.environ.get("TRINO_HOST", ""),
    # "port":     int(os.environ.get("TRINO_PORT", 8080)),
    # "user":     os.environ.get("TRINO_USER", ""),
    # "catalog":  os.environ.get("TRINO_CATALOG", "iceberg"),
    # "schema":   os.environ.get("TRINO_SCHEMA", "drone_delivery"),
}


def _trino_available(config: dict) -> bool:
    """Return True only if the config has enough info to attempt a connection."""
    return bool(config.get("host"))


def insert_delivery_leg(
    drone_id: str,
    leg_type: str,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    cost: float,
    path_length: int,
    duration_seconds: float,
    flight_id: Optional[str] = None,
    trino_config: Optional[dict] = None,
) -> Optional[str]:
    """
    Write a completed flight-leg record to the Trino delivery_logs table.

    Returns the flight_id used (generated if not provided), or None if Trino
    is not configured and the write was skipped.

    Args:
        drone_id:         Identifier of the drone that flew this leg.
        leg_type:         "leg1" | "leg2" | "leg3"
        start_lat/lon:    Origin coordinates.
        end_lat/lon:      Destination coordinates.
        cost:             Pathfinding cost score from the simulator.
        path_length:      Number of grid cells in the solved path.
        duration_seconds: Estimated flight time.
        flight_id:        Optional UUID to group all legs of one delivery.
                          Generated automatically if None.
        trino_config:     Connection dict; falls back to module-level
                          TRINO_CONFIG if not provided.
    """
    if flight_id is None:
        flight_id = str(uuid.uuid4())

    config = trino_config if trino_config is not None else TRINO_CONFIG

    if not _trino_available(config):
        print(
            f"[delivery_logger] Trino not configured — skipping remote log "
            f"for drone {drone_id} ({leg_type}). Set TRINO_HOST to enable."
        )
        return None

    try:
        # Deferred import so missing trino package doesn't crash local runs.
        from trino.dbapi import connect

        timestamp = datetime.now(timezone.utc)
        log_date = timestamp.date()

        conn = connect(**config)
        cursor = conn.cursor()

        cursor.execute(
            f"""
            INSERT INTO {config['catalog']}.{config['schema']}.delivery_logs (
                flight_id, drone_id, leg_type,
                start_lat, start_lon, end_lat, end_lon,
                cost, path_length, duration_seconds,
                timestamp, log_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                flight_id, drone_id, leg_type,
                start_lat, start_lon, end_lat, end_lon,
                cost, path_length, duration_seconds,
                timestamp, log_date,
            ),
        )

        print(f"[delivery_logger] Inserted leg {leg_type} for drone {drone_id} (flight {flight_id})")
        return flight_id

    except Exception as exc:
        # Trino errors must not halt the local simulation.
        print(f"[delivery_logger] Trino write failed for {drone_id}/{leg_type}: {exc}")
        return None
