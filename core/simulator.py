"""
core/simulator.py

Synthetic drone-delivery event generator.

Drives the existing core.events.emit() pipeline so every event also updates
the projection tables (orders, drones, trips).  No threading, no async — a
single deterministic loop driven by `random.Random(seed)` and a synthetic
clock that advances second-by-second.

Typical use::

    from core.simulator import run_simulation
    summary = run_simulation(n_drones=3, n_trips=10, seed=42)
    print(summary)

The function returns a dict of counts; callers (the CLI) print it.

Geographic frame: Portland, OR.  All coordinates are bounded to the metro
area so the data is plausible without any real map.

Known limitation
─────────────────
Emergency-return events abort the trip projection (TripStatus.ABORTED) but
the related order's status is not transitioned to anything terminal — the
order projection only changes on drone_assigned / drone_launched /
delivery_completed / error in the current projections.py.  This keeps the
projection logic small; the event log still records the abort and analytics
queries can use it.  Re-routing emergency returns through the order
projection is a Phase 3+ decision.
"""

from __future__ import annotations

import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.events import (
    ALL_EVENT_TYPES,
    EVT_BATTERY_WARNING,
    EVT_DELIVERY_COMPLETED,
    EVT_DRONE_ASSIGNED,
    EVT_DRONE_LAUNCHED,
    EVT_EMERGENCY_RETURN,
    EVT_MAINTENANCE_REQUIRED,
    EVT_MAINTENANCE_COMPLETED,
    EVT_ORDER_CREATED,
    EVT_PICKUP_COMPLETED,
    EVT_RETURNED_TO_DEPOT,
    EVT_ROUTE_DEVIATION,
    EVT_TELEMETRY_PING,
    emit,
)
from core.models import DeliveryEvent, OrderStatus
from core.scenarios import Scenario, get_scenario
from core.setup_db import create_db


# ── Portland-ish bounds ──────────────────────────────────────────────────────
DEPOT_LAT = 45.5231
DEPOT_LON = -122.6765

PICKUP_LAT_RANGE  = (45.50, 45.55)
PICKUP_LON_RANGE  = (-122.72, -122.62)
DROPOFF_LAT_RANGE = (45.45, 45.60)
DROPOFF_LON_RANGE = (-122.78, -122.55)

STORE_NAMES = [
    "Powell's Books", "Voodoo Doughnut", "Stumptown Roasters",
    "Salt & Straw", "Blue Star Donuts", "Deschutes Brewery",
    "Pok Pok", "Tilt Burger", "Pine State Biscuits",
]


# ─────────────────────────────────────────────────────────────────────────────
# Setup helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_depot(db_path: str, depot_id: str, now: str) -> None:
    """Insert the demo depot once; ignore if it already exists."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO depots(depot_id,name,lat,lon,is_active,created_at) "
            "VALUES(?,?,?,?,1,?)",
            (depot_id, "Portland HQ", DEPOT_LAT, DEPOT_LON, now),
        )
        conn.commit()
    finally:
        conn.close()


def _ensure_fleet(db_path: str, depot_id: str, n_drones: int) -> list[str]:
    """Insert drone_001..N if missing; return the full list of drone IDs."""
    drone_ids = [f"drone_{i:03d}" for i in range(1, n_drones + 1)]
    conn = sqlite3.connect(db_path)
    try:
        for did in drone_ids:
            conn.execute(
                """
                INSERT OR IGNORE INTO drones(
                    drone_id, depot_id, model, speed_mps, range_km,
                    status, current_lat, current_lon, battery_pct
                ) VALUES (?, ?, 'SimDrone v1', 15.0, 25.0, 'idle', ?, ?, 100.0)
                """,
                (did, depot_id, DEPOT_LAT, DEPOT_LON),
            )
        conn.commit()
    finally:
        conn.close()
    return drone_ids


# ─────────────────────────────────────────────────────────────────────────────
# Direct-write helpers (bypass order_manager so we can use the sim clock)
# ─────────────────────────────────────────────────────────────────────────────

def _insert_order_row(
    cur: sqlite3.Cursor,
    *,
    order_id: str,
    customer_id: str,
    store_name: str,
    pickup_lat: float, pickup_lon: float,
    dropoff_lat: float, dropoff_lon: float,
    depot_id: str,
    created_at: str,
) -> None:
    cur.execute(
        """
        INSERT INTO orders (
            order_id, customer_id, store_name,
            pickup_lat, pickup_lon, dropoff_lat, dropoff_lon,
            depot_id, created_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id, customer_id, store_name,
            pickup_lat, pickup_lon, dropoff_lat, dropoff_lon,
            depot_id, created_at, OrderStatus.PENDING,
        ),
    )


def _insert_trip_row(
    cur: sqlite3.Cursor, *, trip_id: str, drone_id: str, order_id: str,
    depot_id: str, scenario_name: Optional[str] = None,
) -> None:
    cur.execute(
        "INSERT INTO trips(trip_id, drone_id, order_id, depot_id, status, scenario_name) "
        "VALUES (?, ?, ?, ?, 'planned', ?)",
        (trip_id, drone_id, order_id, depot_id, scenario_name),
    )


def _insert_leg_row(
    cur: sqlite3.Cursor, *,
    leg_id: str, trip_id: str, leg_index: int,
    start_lat: float, start_lon: float, end_lat: float, end_lon: float,
) -> None:
    cur.execute(
        """
        INSERT INTO trip_legs(leg_id, trip_id, leg_index,
                              start_lat, start_lon, end_lat, end_lon)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (leg_id, trip_id, leg_index, start_lat, start_lon, end_lat, end_lon),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry interpolation
# ─────────────────────────────────────────────────────────────────────────────

def _interpolate(start: tuple[float, float], end: tuple[float, float], steps: int):
    """Yield (lat, lon) tuples, exclusive of start, inclusive of end."""
    for i in range(1, steps + 1):
        t = i / steps
        yield (
            start[0] + (end[0] - start[0]) * t,
            start[1] + (end[1] - start[1]) * t,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(
    db_path: str = "data/delivery_system.sqlite",
    n_drones: int = 3,
    n_trips: int = 10,
    seed: int = 42,
    scenario: "str | Scenario | None" = None,
) -> dict:
    """Run a deterministic synthetic event simulation.

    ``scenario`` may be a registered name (see core.scenarios.list_scenarios),
    a Scenario instance, or None (defaults to ``suburban_standard``, which
    reproduces the pre-Phase-9 hard-coded behaviour for back-compat).
    """
    sc = get_scenario(scenario)
    rng = random.Random(seed)
    create_db(db_path)

    sim_clock = datetime(2026, 5, 21, 14, 0, 0, tzinfo=timezone.utc)
    depot_id = "depot-001"

    def tick(seconds: float) -> str:
        nonlocal sim_clock
        sim_clock = sim_clock + timedelta(seconds=seconds)
        return sim_clock.isoformat()

    def _emit(
        event_type: str,
        *,
        drone_id: Optional[str] = None,
        trip_id:  Optional[str] = None,
        leg_id:   Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        battery: Optional[float] = None,
        payload: Optional[dict] = None,
        dt_seconds: float = 1.0,
        at_time: Optional[str] = None,
    ) -> None:
        if at_time is not None:
            ts = at_time            # explicit timestamp (e.g. maintenance completion)
        else:
            ts = tick(dt_seconds)
        ev = DeliveryEvent(
            event_type=event_type,
            drone_id=drone_id, trip_id=trip_id, leg_id=leg_id,
            latitude=lat, longitude=lon, battery_pct=battery,
            payload_json=DeliveryEvent.encode_payload(payload),
            event_time=ts,
            ingested_at=ts,
            scenario_name=sc.name,
        )
        emit(ev, db_path)
        counts[event_type] = counts.get(event_type, 0) + 1

    counts: dict[str, int] = {t: 0 for t in ALL_EVENT_TYPES}
    trips_completed = 0

    _ensure_depot(db_path, depot_id, sim_clock.isoformat())
    drone_ids = _ensure_fleet(db_path, depot_id, n_drones)
    # Per-drone battery tracked in Python so the simulator can decide whether
    # to fire battery_warning events; the database value is updated by the
    # projection on every telemetry_ping.
    drone_battery: dict[str, float] = {d: 100.0 for d in drone_ids}

    # Dispatch state.
    #   drone_status     — per-drone view ("idle" / "flying" / "maintenance")
    #   pending_completions — drone_id -> sim time at which maintenance ends
    # Cooldown is a fixed 240 s so this change adds no new RNG draws and the
    # rest of the simulator's seeded behavior stays comparable.
    drone_status: dict[str, str] = {d: "idle" for d in drone_ids}
    pending_completions: dict[str, datetime] = {}
    MAINTENANCE_COOLDOWN_S = sc.maintenance_duration_seconds
    RESTORED_BATTERY_PCT   = 100.0

    def schedule_maintenance(did: str, reason: str) -> None:
        """Mark a drone in maintenance and schedule its completion event."""
        drone_status[did] = "maintenance"
        pending_completions[did] = sim_clock + timedelta(seconds=MAINTENANCE_COOLDOWN_S)
        pending_completions[did + "__reason"] = reason  # carried via parallel dict

    def _pop_due_completions() -> None:
        """Fire any maintenance_completed events whose scheduled time has passed."""
        due = [d for d, t in pending_completions.items()
               if not d.endswith("__reason") and t <= sim_clock]
        for did in due:
            scheduled_at = pending_completions.pop(did)
            reason = pending_completions.pop(did + "__reason", "scheduled_inspection")
            _emit(
                EVT_MAINTENANCE_COMPLETED, drone_id=did,
                lat=DEPOT_LAT, lon=DEPOT_LON,
                battery=RESTORED_BATTERY_PCT,
                payload={
                    "reason": reason,
                    "maintenance_duration_seconds": MAINTENANCE_COOLDOWN_S,
                    "restored_battery_pct": RESTORED_BATTERY_PCT,
                },
                at_time=scheduled_at.isoformat(),
            )
            drone_status[did]  = "idle"
            drone_battery[did] = RESTORED_BATTERY_PCT

    def pick_drone(trip_idx: int) -> str:
        """Pick an idle drone; advance clock and emit completions as needed."""
        nonlocal sim_clock
        for _attempt in range(len(drone_ids) + 1):
            _pop_due_completions()
            # Round-robin starting offset = trip_idx for deterministic rotation.
            start = trip_idx % len(drone_ids)
            for offset in range(len(drone_ids)):
                d = drone_ids[(start + offset) % len(drone_ids)]
                if drone_status[d] == "idle":
                    return d
            # Nothing idle — advance to earliest scheduled completion.
            ready = {k: v for k, v in pending_completions.items()
                     if not k.endswith("__reason")}
            if not ready:
                raise RuntimeError(
                    "no idle drones and no maintenance completions pending"
                )
            sim_clock = max(sim_clock, min(ready.values()))
        raise RuntimeError("dispatch loop did not converge")

    for trip_idx in range(n_trips):
        # ── pick a drone (maintenance-aware), generate order coordinates ────
        drone_id = pick_drone(trip_idx)
        drone_status[drone_id] = "flying"
        order_id = str(uuid.uuid4())
        trip_id  = str(uuid.uuid4())

        store     = rng.choice(STORE_NAMES)
        pickup    = (rng.uniform(*PICKUP_LAT_RANGE),  rng.uniform(*PICKUP_LON_RANGE))
        dropoff   = (rng.uniform(*DROPOFF_LAT_RANGE), rng.uniform(*DROPOFF_LON_RANGE))
        depot_pt  = (DEPOT_LAT, DEPOT_LON)

        # ── seed orders/trips/trip_legs rows (single transaction) ───────────
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            _insert_order_row(
                cur,
                order_id=order_id,
                customer_id=f"C{trip_idx+1:04d}",
                store_name=store,
                pickup_lat=pickup[0], pickup_lon=pickup[1],
                dropoff_lat=dropoff[0], dropoff_lon=dropoff[1],
                depot_id=depot_id,
                created_at=sim_clock.isoformat(),
            )
            _insert_trip_row(cur, trip_id=trip_id, drone_id=drone_id,
                             order_id=order_id, depot_id=depot_id,
                             scenario_name=sc.name)
            leg1_id, leg2_id, leg3_id = (str(uuid.uuid4()) for _ in range(3))
            _insert_leg_row(cur, leg_id=leg1_id, trip_id=trip_id, leg_index=1,
                            start_lat=depot_pt[0], start_lon=depot_pt[1],
                            end_lat=pickup[0],  end_lon=pickup[1])
            _insert_leg_row(cur, leg_id=leg2_id, trip_id=trip_id, leg_index=2,
                            start_lat=pickup[0],  start_lon=pickup[1],
                            end_lat=dropoff[0], end_lon=dropoff[1])
            _insert_leg_row(cur, leg_id=leg3_id, trip_id=trip_id, leg_index=3,
                            start_lat=dropoff[0], start_lon=dropoff[1],
                            end_lat=depot_pt[0], end_lon=depot_pt[1])
            conn.commit()
        finally:
            conn.close()

        # ── event sequence ──────────────────────────────────────────────────
        _emit(
            EVT_ORDER_CREATED, trip_id=trip_id,
            payload={"order_id": order_id, "store_name": store,
                     "customer_id": f"C{trip_idx+1:04d}"},
            dt_seconds=1,
        )
        _emit(
            EVT_DRONE_ASSIGNED, drone_id=drone_id, trip_id=trip_id,
            payload={"order_id": order_id},
            dt_seconds=2,
        )

        # ── leg 1: depot → pickup, with telemetry ──────────────────────────
        battery = drone_battery[drone_id]
        _emit(
            EVT_DRONE_LAUNCHED, drone_id=drone_id, trip_id=trip_id, leg_id=leg1_id,
            lat=depot_pt[0], lon=depot_pt[1], battery=battery,
            payload={"leg_index": 1, "destination": "pickup"},
            dt_seconds=5,
        )

        ping_steps = rng.randint(3, 6) + sc.telemetry_bonus_per_leg
        for lat, lon in _interpolate(depot_pt, pickup, ping_steps):
            battery = max(0.0, battery - rng.uniform(1.5, 3.0) * sc.battery_drain_multiplier)
            _emit(
                EVT_TELEMETRY_PING, drone_id=drone_id, trip_id=trip_id, leg_id=leg1_id,
                lat=lat, lon=lon, battery=battery,
                dt_seconds=rng.randint(20, 45),
            )
            _maybe_inject_warnings(_emit, rng, sc, drone_id, trip_id, leg1_id, lat, lon, battery)

        _emit(
            EVT_PICKUP_COMPLETED, drone_id=drone_id, trip_id=trip_id, leg_id=leg1_id,
            lat=pickup[0], lon=pickup[1], battery=battery,
            payload={"store_name": store, "order_id": order_id},
            dt_seconds=10,
        )

        # ── leg 2: pickup → dropoff, with telemetry ─────────────────────────
        # Small chance of emergency return on leg 2.
        emergency = rng.random() < sc.emergency_return_chance
        ping_steps = rng.randint(4, 8) + sc.telemetry_bonus_per_leg
        end_point = depot_pt if emergency else dropoff
        leg2_target = leg2_id if not emergency else leg2_id  # leg_id stays leg2

        for lat, lon in _interpolate(pickup, end_point, ping_steps):
            battery = max(0.0, battery - rng.uniform(2.0, 4.0) * sc.battery_drain_multiplier)
            _emit(
                EVT_TELEMETRY_PING, drone_id=drone_id, trip_id=trip_id, leg_id=leg2_target,
                lat=lat, lon=lon, battery=battery,
                dt_seconds=rng.randint(20, 45),
            )
            _maybe_inject_warnings(_emit, rng, sc, drone_id, trip_id, leg2_target, lat, lon, battery)

        if emergency:
            _emit(
                EVT_EMERGENCY_RETURN, drone_id=drone_id, trip_id=trip_id, leg_id=leg2_target,
                lat=depot_pt[0], lon=depot_pt[1], battery=battery,
                payload={"reason": "low_battery_or_obstacle", "order_id": order_id},
                dt_seconds=5,
            )
            drone_battery[drone_id] = battery
            # Emergency-return drones always go through maintenance before
            # returning to service — matches the projection logic that already
            # transitions the drone to MAINTENANCE on this event.
            schedule_maintenance(drone_id, "post_emergency_return")
        else:
            _emit(
                EVT_DELIVERY_COMPLETED, drone_id=drone_id, trip_id=trip_id, leg_id=leg2_id,
                lat=dropoff[0], lon=dropoff[1], battery=battery,
                payload={"order_id": order_id, "store_name": store},
                dt_seconds=10,
            )
            # ── leg 3: dropoff → depot, with telemetry ──────────────────────
            return_steps = rng.randint(3, 6) + sc.telemetry_bonus_per_leg
            for lat, lon in _interpolate(dropoff, depot_pt, return_steps):
                battery = max(0.0, battery - rng.uniform(1.5, 3.0) * sc.battery_drain_multiplier)
                _emit(
                    EVT_TELEMETRY_PING, drone_id=drone_id, trip_id=trip_id, leg_id=leg3_id,
                    lat=lat, lon=lon, battery=battery,
                    dt_seconds=rng.randint(20, 45),
                )
                _maybe_inject_warnings(_emit, rng, sc, drone_id, trip_id, leg3_id, lat, lon, battery)

            _emit(
                EVT_RETURNED_TO_DEPOT, drone_id=drone_id, trip_id=trip_id, leg_id=leg3_id,
                lat=depot_pt[0], lon=depot_pt[1], battery=battery,
                payload={"order_id": order_id},
                dt_seconds=5,
            )
            trips_completed += 1
            drone_battery[drone_id] = battery
            drone_status[drone_id] = "idle"

        # ── between trips: maybe schedule maintenance ──────────────────────
        # Draw the RNG unconditionally so the seeded sequence stays stable.
        maint_roll = rng.random()
        if drone_battery[drone_id] < 25 or maint_roll < sc.maintenance_chance:
            if drone_status[drone_id] == "idle":
                reason = "low_battery" if drone_battery[drone_id] < 25 else "scheduled_inspection"
                _emit(
                    EVT_MAINTENANCE_REQUIRED, drone_id=drone_id,
                    payload={"reason": reason},
                    dt_seconds=30,
                )
                schedule_maintenance(drone_id, reason)
            # If the drone is already in maintenance (e.g. after an emergency
            # return), don't re-emit the request — the existing completion
            # event already covers it.

    # Count what actually landed in the DB as a cross-check.
    conn = sqlite3.connect(db_path)
    try:
        events_written = conn.execute(
            "SELECT COUNT(*) FROM delivery_events"
        ).fetchone()[0]
    finally:
        conn.close()

    # Trim zero-count keys for a cleaner summary.
    event_counts_by_type = {k: v for k, v in counts.items() if v > 0}

    return {
        "drones":               len(drone_ids),
        "trips_requested":      n_trips,
        "trips_completed":      trips_completed,
        "events_written":       events_written,
        "event_counts_by_type": event_counts_by_type,
        "db_path":              db_path,
        "scenario":             sc.name,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Random operational noise — small helper kept out of the main loop for clarity
# ─────────────────────────────────────────────────────────────────────────────

def _maybe_inject_warnings(
    emit_fn, rng: random.Random, sc: Scenario,
    drone_id: str, trip_id: str, leg_id: str,
    lat: float, lon: float, battery: float,
) -> None:
    """Occasionally emit battery_warning or route_deviation mid-flight.

    Thresholds and probabilities come from the active Scenario so different
    operational environments produce visibly different operational noise.
    """
    if battery < sc.battery_warning_threshold and rng.random() < 0.4:
        emit_fn(
            EVT_BATTERY_WARNING, drone_id=drone_id, trip_id=trip_id, leg_id=leg_id,
            lat=lat, lon=lon, battery=battery,
            payload={"threshold": sc.battery_warning_threshold,
                     "warning_reason": "below_threshold"},
            dt_seconds=1,
        )
    if rng.random() < sc.route_deviation_chance:
        emit_fn(
            EVT_ROUTE_DEVIATION, drone_id=drone_id, trip_id=trip_id, leg_id=leg_id,
            lat=lat, lon=lon, battery=battery,
            payload={"issue_type": "wind_correction",
                     "deviation_m": round(rng.uniform(15, 80), 1)},
            dt_seconds=1,
        )
