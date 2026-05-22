"""
core/events.py

Event type vocabulary + the single entry point for recording events.

  emit(event, sink)       — primary write path.  Appends the event and
                            updates any projection rows in one transaction.
                            `sink` is either a db path (str) or a Sink object.
  write_event(event, ...) — append-only; does NOT touch projections.  Use
                            for migrations and replay scenarios.
  fetch_events(...)       — read helper for tests and inspection scripts.

Module dependency position:
    models.py  ←  events.py  ←  projections.py
                      ↑
                order_manager.py / simulator.py
"""

import sqlite3
from typing import Optional, Union

from core.models import DeliveryEvent
from core.projections import (
    _apply_drone_projection,
    _apply_order_projection,
    _apply_trip_projection,
    _insert_event_row,
)


# ─────────────────────────────────────────────────────────────────────────────
# Event type constants.
#
# Naming convention: past-tense verb describing something that already
# happened ("launched", "completed"), not a command.
# ─────────────────────────────────────────────────────────────────────────────

# Order lifecycle (kept from v1 for the order side of the world).
EVT_ORDER_CREATED   = "order_created"
EVT_DRONE_ASSIGNED  = "drone_assigned"

# Trip / flight events (the target vocabulary).
EVT_DRONE_LAUNCHED      = "drone_launched"
EVT_PICKUP_COMPLETED    = "pickup_completed"
EVT_TELEMETRY_PING      = "telemetry_ping"
EVT_DELIVERY_COMPLETED  = "delivery_completed"
EVT_RETURNED_TO_DEPOT   = "returned_to_depot"
EVT_BATTERY_WARNING     = "battery_warning"
EVT_ROUTE_DEVIATION     = "route_deviation"
EVT_EMERGENCY_RETURN    = "emergency_return"
EVT_MAINTENANCE_REQUIRED  = "maintenance_required"
EVT_MAINTENANCE_COMPLETED = "maintenance_completed"

# Catch-all error event.
EVT_ERROR = "error"


ALL_EVENT_TYPES: list[str] = [
    EVT_ORDER_CREATED,
    EVT_DRONE_ASSIGNED,
    EVT_DRONE_LAUNCHED,
    EVT_PICKUP_COMPLETED,
    EVT_TELEMETRY_PING,
    EVT_DELIVERY_COMPLETED,
    EVT_RETURNED_TO_DEPOT,
    EVT_BATTERY_WARNING,
    EVT_ROUTE_DEVIATION,
    EVT_EMERGENCY_RETURN,
    EVT_MAINTENANCE_REQUIRED,
    EVT_MAINTENANCE_COMPLETED,
    EVT_ERROR,
]


# ─────────────────────────────────────────────────────────────────────────────
# Primary write path
# ─────────────────────────────────────────────────────────────────────────────

def emit(event: DeliveryEvent, db_path: str) -> None:
    """Append the event and update projection rows in one SQLite transaction."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        _insert_event_row(cur, event)
        _apply_order_projection(cur, event)
        _apply_drone_projection(cur, event)
        _apply_trip_projection(cur, event)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def write_event(event: DeliveryEvent, db_path: str) -> None:
    """Append-only write to delivery_events.  Skips projection updates."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        _insert_event_row(cur, event)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Read helper
# ─────────────────────────────────────────────────────────────────────────────

def fetch_events(
    db_path: str,
    event_type: Optional[str] = None,
    drone_id:   Optional[str] = None,
    trip_id:    Optional[str] = None,
    limit: int = 100,
) -> list[DeliveryEvent]:
    """Read events from the log with optional filters (debug / test use only)."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        conditions: list[str] = []
        params: list = []
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if drone_id is not None:
            conditions.append("drone_id = ?")
            params.append(drone_id)
        if trip_id is not None:
            conditions.append("trip_id = ?")
            params.append(trip_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cur.execute(
            f"""
            SELECT event_id, event_time, ingested_at,
                   drone_id, trip_id, leg_id, event_type,
                   latitude, longitude, battery_pct, payload_json,
                   scenario_name
              FROM delivery_events
            {where}
             ORDER BY event_time DESC
             LIMIT ?
            """,
            params + [limit],
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return [
        DeliveryEvent(
            event_id=r[0], event_time=r[1], ingested_at=r[2],
            drone_id=r[3], trip_id=r[4], leg_id=r[5], event_type=r[6],
            latitude=r[7], longitude=r[8], battery_pct=r[9],
            payload_json=r[10], scenario_name=r[11],
        )
        for r in rows
    ]
