"""
core/models.py

Canonical data containers for the analytics-first drone delivery simulation.

Responsibilities
─────────────────
  1. DeliveryEvent  — the atomic row written to the delivery_events log.
  2. Drone / Trip / TripLeg / Order — light dataclasses for the projection
     tables.  They are passed around in Python; the database is the source
     of truth.
  3. OrderStatus / DroneStatus / TripStatus — string-constant namespaces so
     every module uses the same status vocabulary.

This module has zero dependencies on other core modules — it sits at the
base of the import graph so nothing here can cause a circular import.

Design notes
─────────────
  - Timestamps are UTC ISO-8601 strings, not datetime objects.  SQLite
    stores them as TEXT and datetime.fromisoformat() round-trips cleanly.
  - payload_json is a JSON string so the delivery_events table never needs
    a schema migration when a new event type adds new fields.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# Status vocabularies
# ─────────────────────────────────────────────────────────────────────────────

class OrderStatus:
    PENDING   = "pending"
    ASSIGNED  = "assigned"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    ERROR     = "error"


class DroneStatus:
    IDLE        = "idle"
    ASSIGNED    = "assigned"
    FLYING      = "flying"
    MAINTENANCE = "maintenance"
    ERROR       = "error"


class TripStatus:
    PLANNED    = "planned"
    IN_FLIGHT  = "in_flight"
    COMPLETED  = "completed"
    ABORTED    = "aborted"


# ─────────────────────────────────────────────────────────────────────────────
# DeliveryEvent — immutable row in the append-only event log.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DeliveryEvent:
    """One row in the delivery_events log.

    Columns mirror the target schema:
        event_id, event_time, ingested_at,
        drone_id, trip_id, leg_id,
        event_type,
        latitude, longitude, battery_pct,
        payload_json
    """

    event_type: str

    drone_id: Optional[str] = None
    trip_id:  Optional[str] = None
    leg_id:   Optional[str] = None

    latitude:    Optional[float] = None
    longitude:   Optional[float] = None
    battery_pct: Optional[float] = None

    payload_json: Optional[str] = None

    # Scenario tag — set by the simulator on every event it emits so analytics
    # queries can group/filter by operational environment.  Null for events
    # emitted outside a scenario (e.g. ad-hoc create_order calls in tests).
    scenario_name: Optional[str] = None

    event_id:    str = field(default_factory=_new_uuid)
    event_time:  str = field(default_factory=_now_utc)
    ingested_at: str = field(default_factory=_now_utc)

    def to_dict(self) -> dict:
        return asdict(self)

    def payload(self) -> Optional[dict]:
        if self.payload_json is None:
            return None
        return json.loads(self.payload_json)

    @staticmethod
    def encode_payload(payload: Optional[dict]) -> Optional[str]:
        if payload is None:
            return None
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


# ─────────────────────────────────────────────────────────────────────────────
# Light projection-row dataclasses.
# These exist for type hints and constructor convenience; the database holds
# the authoritative state.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Drone:
    drone_id:  str
    depot_id:  str
    model:     Optional[str] = None
    speed_mps: Optional[float] = None
    range_km:  Optional[float] = None


@dataclass
class Order:
    order_id:    str
    customer_id: str
    store_name:  str
    pickup_lat:  float
    pickup_lon:  float
    dropoff_lat: float
    dropoff_lon: float
    depot_id:    str = "depot-001"


@dataclass
class Trip:
    trip_id:  str
    drone_id: str
    order_id: str
    depot_id: str


@dataclass
class TripLeg:
    leg_id:    str
    trip_id:   str
    leg_index: int  # 1=hub→pickup, 2=pickup→dropoff, 3=dropoff→hub
    start_lat: float
    start_lon: float
    end_lat:   float
    end_lon:   float
