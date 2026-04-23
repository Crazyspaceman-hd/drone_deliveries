"""
core/events.py

Event type constants and the event logging interface for v2.

Responsibilities of this module:
  1. Define the canonical string constants for each event_type value so that
     every part of the codebase uses exactly the same strings.
  2. Provide a single write_event() function that persists a DeliveryEvent
     to the delivery_events table.

What this module intentionally does NOT do:
  - No simulation logic.
  - No pathfinding or terrain calculations.
  - No network calls (Trino, Snowflake, S3) — those belong in future
    analytics/exporters/ modules once the local event log is stable.
  - No background threads or queues.

The goal right now is a minimal, testable interface.  Every future pipeline
stage (simulator, dispatcher, batch exporter) will call write_event() to
record what it does.  The event log is the integration point.
"""

import json
import sqlite3
from typing import Optional

from core.models import DeliveryEvent


# ---------------------------------------------------------------------------
# Event type constants
#
# Use these instead of raw strings throughout the codebase.
# Adding a new event type means adding one constant here plus any handling
# logic in the consumer — no schema migrations needed.
# ---------------------------------------------------------------------------

EVT_ORDER_CREATED      = "order_created"
# Fired when a new delivery request is written to the orders table.

EVT_DRONE_ASSIGNED     = "drone_assigned"
# Fired when a specific drone is matched to a pending order.

EVT_LEG_STARTED        = "leg_started"
# Fired at the start of each flight leg (before pathfinding runs).

EVT_LEG_COMPLETED      = "leg_completed"
# Fired when a flight leg finishes; payload includes cost and duration.

EVT_DELIVERY_CONFIRMED = "delivery_confirmed"
# Fired after all three legs complete successfully for an order.

EVT_ERROR              = "error"
# Fired when any step fails; payload.message contains the reason.

# Ordered list useful for documentation and validation.
ALL_EVENT_TYPES = [
    EVT_ORDER_CREATED,
    EVT_DRONE_ASSIGNED,
    EVT_LEG_STARTED,
    EVT_LEG_COMPLETED,
    EVT_DELIVERY_CONFIRMED,
    EVT_ERROR,
]


# ---------------------------------------------------------------------------
# Event persistence
# ---------------------------------------------------------------------------

def write_event(event: DeliveryEvent, db_path: str) -> None:
    """
    Append a single DeliveryEvent to the delivery_events table.

    This is the only function in the codebase that writes to delivery_events.
    Centralizing writes here means:
      - Adding audit logging, metrics, or async forwarding later requires
        changing one place, not every caller.
      - Tests can mock or redirect writes by patching this function.

    Args:
        event:   The DeliveryEvent to persist.
        db_path: Path to the SQLite database file.  Callers should pass
                 the same path they used when calling setup_db.create_db().

    Raises:
        sqlite3.Error: propagated from sqlite3 if the INSERT fails
                       (e.g. schema mismatch, disk full).
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO delivery_events (
                event_id, event_type, order_id, drone_id,
                leg_number, payload_json, occurred_at, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                event.order_id,
                event.drone_id,
                event.leg_number,
                event.payload_json,
                event.occurred_at,
                event.recorded_at,
            ),
        )
        conn.commit()
    finally:
        # Always close the connection even if the INSERT raises.
        conn.close()


def fetch_events(
    db_path: str,
    event_type: Optional[str] = None,
    order_id: Optional[str] = None,
    limit: int = 100,
) -> list[DeliveryEvent]:
    """
    Read events back from the log with optional filters.

    This is a convenience function for debugging and testing.  Production
    analytics should query delivery_events directly via SQL (see analytics/sql/).

    Args:
        db_path:    Path to the SQLite database.
        event_type: If provided, only return events of this type.
        order_id:   If provided, only return events for this order.
        limit:      Maximum number of rows to return (most recent first).

    Returns:
        List of DeliveryEvent objects ordered by occurred_at descending.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        # Build WHERE clause dynamically based on which filters are provided.
        conditions = []
        params: list = []

        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)

        if order_id is not None:
            conditions.append("order_id = ?")
            params.append(order_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        cur.execute(
            f"""
            SELECT event_id, event_type, order_id, drone_id,
                   leg_number, payload_json, occurred_at, recorded_at
            FROM   delivery_events
            {where}
            ORDER BY occurred_at DESC
            LIMIT ?
            """,
            params + [limit],
        )

        rows = cur.fetchall()
    finally:
        conn.close()

    return [
        DeliveryEvent(
            event_id=row[0],
            event_type=row[1],
            order_id=row[2],
            drone_id=row[3],
            leg_number=row[4],
            payload_json=row[5],
            occurred_at=row[6],
            recorded_at=row[7],
        )
        for row in rows
    ]
