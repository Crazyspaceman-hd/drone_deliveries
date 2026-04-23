"""
core/models.py

Canonical data models for the v2 analytics-first drone delivery simulation.

These dataclasses are the single source of truth for what each entity looks
like as it moves through the system.  Any code that produces or consumes
delivery data should import from here rather than defining its own ad-hoc
dicts or tuples.

Design notes:
  - All models use Python dataclasses (stdlib only, no ORM).
  - Fields match the delivery_events table columns so serialization is
    straightforward: asdict(event) maps directly to an INSERT.
  - Timestamps are always UTC strings in ISO-8601 format so they survive
    JSON serialization and SQLite storage without conversion.
  - Optional fields default to None; callers should set them explicitly
    rather than relying on defaults for required business data.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# DeliveryEvent
#
# The central unit of data in the v2 system.  Every meaningful state change
# is represented as a DeliveryEvent appended to the delivery_events table.
#
# Why an event log instead of mutable rows?
#   Mutable status columns (order.status = 'delivered') are convenient but
#   they erase history.  An event log lets you answer questions like:
#     "How long did leg 2 take on average last week?"
#     "Which orders had an error before eventually completing?"
#     "What was the drone doing at 14:32 UTC?"
#   These are the queries that make a simulation analytically valuable.
# ---------------------------------------------------------------------------

@dataclass
class DeliveryEvent:
    """
    A single immutable event record in the delivery event log.

    Attributes:
        event_id (str):
            UUID that uniquely identifies this event across all tables and
            any future external systems (Iceberg, Snowflake, etc.).

        event_type (str):
            Machine-readable verb describing what happened.  Use the
            constants defined in core.events rather than raw strings so
            typos are caught at import time.

            Valid values (defined in core/events.py):
                order_created       — a new delivery request entered the system
                drone_assigned      — a drone was matched to an order
                leg_started         — a flight leg began
                leg_completed       — a flight leg finished successfully
                delivery_confirmed  — all legs done, order marked delivered
                error               — something went wrong (see payload_json)

        order_id (Optional[str]):
            FK to the orders table.  None for system-level events that are
            not tied to a specific order (e.g. drone health check events).

        drone_id (Optional[str]):
            FK to the drones table.  None until a drone is assigned.

        leg_number (Optional[int]):
            Which leg of the delivery this event belongs to:
                1 = hub → pickup
                2 = pickup → dropoff (customer)
                3 = dropoff → hub (return)
            None for non-flight events (order_created, delivery_confirmed).

        payload_json (Optional[str]):
            JSON-encoded dict of event-specific details.  The schema of
            this payload varies by event_type.  Examples:

            For leg_completed:
                {
                  "start_lat": 45.532,  "start_lon": -122.653,
                  "end_lat":   45.484,  "end_lon":   -122.575,
                  "cost":      312.4,   "path_length": 948,
                  "duration_seconds": 94.8
                }

            For error:
                {
                  "message": "No path found between grid cells",
                  "traceback": "..."
                }

            Keeping details in JSON avoids schema churn as the simulation
            evolves — new fields can be added without ALTER TABLE.

        occurred_at (str):
            UTC ISO-8601 timestamp of when this event happened in the
            simulation clock.  For real-time simulations this is wall-clock
            time; for replayed simulations it may be a synthetic past time.

        recorded_at (str):
            UTC ISO-8601 timestamp of when this row was constructed.
            Usually the same as occurred_at in a real-time simulation but
            can differ when events are buffered or replayed.
    """

    event_type: str

    # Optional FK references — most events tie to both an order and a drone.
    order_id: Optional[str] = None
    drone_id: Optional[str] = None

    # Leg context — only meaningful for flight events.
    leg_number: Optional[int] = None

    # Arbitrary JSON blob for event-specific fields.
    payload_json: Optional[str] = None

    # Auto-generated identifiers and timestamps.
    event_id: str = field(default_factory=_new_uuid)
    occurred_at: str = field(default_factory=_now_utc)
    recorded_at: str = field(default_factory=_now_utc)

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def order_created(cls, order_id: str, payload: Optional[dict] = None) -> "DeliveryEvent":
        """Shorthand for creating an order_created event."""
        from core.events import EVT_ORDER_CREATED
        return cls(
            event_type=EVT_ORDER_CREATED,
            order_id=order_id,
            payload_json=json.dumps(payload) if payload else None,
        )

    @classmethod
    def leg_completed(
        cls,
        order_id: str,
        drone_id: str,
        leg_number: int,
        payload: dict,
    ) -> "DeliveryEvent":
        """Shorthand for creating a leg_completed event."""
        from core.events import EVT_LEG_COMPLETED
        return cls(
            event_type=EVT_LEG_COMPLETED,
            order_id=order_id,
            drone_id=drone_id,
            leg_number=leg_number,
            payload_json=json.dumps(payload),
        )

    @classmethod
    def error(
        cls,
        message: str,
        order_id: Optional[str] = None,
        drone_id: Optional[str] = None,
    ) -> "DeliveryEvent":
        """Shorthand for creating an error event."""
        from core.events import EVT_ERROR
        return cls(
            event_type=EVT_ERROR,
            order_id=order_id,
            drone_id=drone_id,
            payload_json=json.dumps({"message": message}),
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain dict ready for INSERT into delivery_events."""
        return asdict(self)

    def payload(self) -> Optional[dict]:
        """Deserialize payload_json back into a dict, or None."""
        if self.payload_json is None:
            return None
        return json.loads(self.payload_json)
