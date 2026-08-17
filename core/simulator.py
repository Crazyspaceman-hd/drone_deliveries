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

import math
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
    EVT_OBSTACLE_WARNING,
    EVT_ORDER_CREATED,
    EVT_PICKUP_COMPLETED,
    EVT_RETURNED_TO_DEPOT,
    EVT_ROUTE_DEVIATION,
    EVT_TELEMETRY_PING,
    emit,
)
from core.hybrid import generate_order_characteristics
from core.models import DeliveryEvent, OrderStatus
from core.runs import (
    ASSUMPTION_VERSION, SIMULATOR_VERSION, create_simulation_run,
)
from core.scenarios import Scenario, get_scenario
from core.setup_db import create_db
from core.telemetry_model import (
    OBSTACLE_WARNING_BASE_PROB,
    PHASE_ASCEND, PHASE_CRUISE, PHASE_DESCEND, PHASE_HOVER,
    TelemetryObservation,
    bearing_deg, generate_observation, remaining_range_triggers_emergency,
)


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
    run_id: Optional[str] = None,
    scenario_name: Optional[str] = None,
    # Phase 19 — hybrid logistics fields.
    payload_weight_kg: Optional[float] = None,
    urgency_level: Optional[str] = None,
    estimated_prep_time_min: Optional[float] = None,
    promised_delivery_window_min: Optional[float] = None,
    premium_delivery: Optional[bool] = None,
    congestion_factor: Optional[float] = None,
    queue_pressure: Optional[float] = None,
    fulfillment_mode: Optional[str] = None,
    activation_reason: Optional[str] = None,
    truck_baseline_cost: Optional[float] = None,
    truck_baseline_latency_min: Optional[float] = None,
    drone_estimated_latency_min: Optional[float] = None,
) -> None:
    cur.execute(
        """
        INSERT INTO orders (
            order_id, customer_id, store_name,
            pickup_lat, pickup_lon, dropoff_lat, dropoff_lon,
            depot_id, created_at, status, run_id, scenario_name,
            payload_weight_kg, urgency_level, estimated_prep_time_min,
            promised_delivery_window_min, premium_delivery, congestion_factor,
            queue_pressure, fulfillment_mode, activation_reason,
            truck_baseline_cost, truck_baseline_latency_min,
            drone_estimated_latency_min
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id, customer_id, store_name,
            pickup_lat, pickup_lon, dropoff_lat, dropoff_lon,
            depot_id, created_at, OrderStatus.PENDING, run_id, scenario_name,
            payload_weight_kg, urgency_level, estimated_prep_time_min,
            promised_delivery_window_min,
            None if premium_delivery is None else (1 if premium_delivery else 0),
            congestion_factor, queue_pressure,
            fulfillment_mode, activation_reason,
            truck_baseline_cost, truck_baseline_latency_min,
            drone_estimated_latency_min,
        ),
    )


def _insert_trip_row(
    cur: sqlite3.Cursor, *, trip_id: str, drone_id: str, order_id: str,
    depot_id: str, scenario_name: Optional[str] = None,
    run_id: Optional[str] = None,
) -> None:
    cur.execute(
        "INSERT INTO trips(trip_id, drone_id, order_id, depot_id, status, "
        "                  scenario_name, run_id) "
        "VALUES (?, ?, ?, ?, 'planned', ?, ?)",
        (trip_id, drone_id, order_id, depot_id, scenario_name, run_id),
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

def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two (lat, lon) points in kilometers."""
    R = 6371.0088
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# Phase 20: per-trip economics derivation moved to `transforms/economics.py`.
# The simulator no longer owns cost calculations — they are recomputed
# downstream so sensitivity analysis doesn't require regenerating events.


def _interpolate(start: tuple[float, float], end: tuple[float, float], steps: int):
    """Yield (lat, lon) tuples, exclusive of start, inclusive of end."""
    for i in range(1, steps + 1):
        t = i / steps
        yield (
            start[0] + (end[0] - start[0]) * t,
            start[1] + (end[1] - start[1]) * t,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Operational-environment coupling
# ─────────────────────────────────────────────────────────────────────────────
#
# Pickup / dropoff points are drawn as random offsets from the depot whose
# *radius* is anchored to the scenario's avg_trip_distance_km.  With pickup
# and dropoff both at radius R from depot and independent random bearings,
# the expected three-leg trip distance is roughly
#       E[leg1 + leg2 + leg3]  =  R + (4/π)R + R  ≈  3.27 R
# so we target R ≈ avg_trip_distance_km / 3.27.
_DISTANCE_RADIUS_DIVISOR = 3.27
# ── km per degree at the depot's latitude (used for the local-flat
# approximation; good enough for distances ≪ 100 km).
_KM_PER_DEG_LAT = 111.0
# ── Drone range used for the on-board "estimated remaining range" telemetry
# observation.  Matches the value written into the drones table by
# ``_ensure_fleet``.  Single source of truth; bump in both places together.
DRONE_RANGE_KM = 25.0


def _random_point_around(
    rng: random.Random,
    center: tuple[float, float],
    target_radius_km: float,
    radius_jitter: tuple[float, float] = (0.6, 1.2),
) -> tuple[float, float]:
    """Random (lat, lon) point whose distance from ``center`` is roughly
    ``target_radius_km``.  Uses exactly two RNG draws (radius fraction +
    bearing) so it can replace the old two-uniform coordinate draw without
    shifting the rest of the seeded sequence's *count*.
    """
    r = target_radius_km * rng.uniform(*radius_jitter)
    bearing = rng.uniform(0.0, 2.0 * math.pi)
    km_per_deg_lat = _KM_PER_DEG_LAT
    km_per_deg_lon = _KM_PER_DEG_LAT * math.cos(math.radians(center[0]))
    return (
        center[0] + (r * math.cos(bearing)) / km_per_deg_lat,
        center[1] + (r * math.sin(bearing)) / km_per_deg_lon,
    )


# Telemetry density per km of leg distance.  Tuned so a 1 km urban leg
# still gets a handful of pings (after the per-scenario bonus); a 6 km
# rural leg gets noticeably more.
_PINGS_PER_KM = 1.5


def _telemetry_steps(rng: random.Random, leg_distance_km: float,
                     sc: Scenario) -> int:
    """How many telemetry pings to emit on a leg of the given distance.

    Distance is now the primary driver; scenario.telemetry_bonus_per_leg is
    an additive "urban density" knob.  One RNG draw (the jitter) keeps the
    draw count per leg stable at one, matching the old ``rng.randint(...)``.
    """
    base = int(round(leg_distance_km * _PINGS_PER_KM))
    jitter = rng.randint(-1, 1)
    return max(2, base + sc.telemetry_bonus_per_leg + jitter)


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(
    db_path: str = "data/delivery_system.sqlite",
    n_drones: int = 3,
    n_trips: int = 10,
    seed: int = 42,
    scenario: "str | Scenario | None" = None,
    run_transforms: bool = True,
) -> dict:
    """Run a deterministic synthetic event simulation.

    ``scenario`` may be a registered name (see core.scenarios.list_scenarios),
    a Scenario instance, or None (defaults to ``suburban_standard``, which
    reproduces the pre-Phase-9 hard-coded behavior for back-compat).

    ``run_transforms`` (Phase 20, default True): after the simulator finishes,
    run the transform pipeline (economics + hybrid) so derived columns are
    populated.  Pass False if you want to inspect the raw event/projection
    state before any analytical derivation runs.
    """
    sc = get_scenario(scenario)
    rng = random.Random(seed)
    create_db(db_path)

    # ── Phase 15: register this experiment in simulation_runs ──────────────
    # run_id is generated up front so every event/trip/order this call emits
    # can carry it.  Metadata writes do not touch the seeded RNG, so the
    # operational sequence remains deterministic for a given (seed, scenario).
    run_id = create_simulation_run(
        db_path,
        seed=seed,
        scenario_names=sc.name,
        trip_count=n_trips,
        drone_count=n_drones,
    )

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
    ) -> str:
        """Emit one DeliveryEvent.  Returns its event_id so callers can
        attach side-tables (Phase 21: telemetry_observations)."""
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
            run_id=run_id,
        )
        emit(ev, db_path)
        counts[event_type] = counts.get(event_type, 0) + 1
        return ev.event_id

    def _insert_obs(event_id: str, obs: TelemetryObservation) -> None:
        """Side-table insert keyed by the ping event's ID (Phase 21)."""
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                INSERT INTO telemetry_observations (
                    event_id, altitude_m, airspeed_mps, heading_deg,
                    vertical_speed_mps, battery_temp_c, motor_temp_c,
                    estimated_remaining_range_km, signal_strength_pct,
                    gps_signal_quality
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, obs.altitude_m, obs.airspeed_mps, obs.heading_deg,
                    obs.vertical_speed_mps, obs.battery_temp_c, obs.motor_temp_c,
                    obs.estimated_remaining_range_km, obs.signal_strength_pct,
                    obs.gps_signal_quality,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    counts: dict[str, int] = {t: 0 for t in ALL_EVENT_TYPES}
    trips_completed = 0

    _ensure_depot(db_path, depot_id, sim_clock.isoformat())
    drone_ids = _ensure_fleet(db_path, depot_id, n_drones)
    # Per-drone battery tracked in Python so the simulator can decide whether
    # to fire battery_warning events; the database value is updated by the
    # projection on every telemetry_ping.
    drone_battery: dict[str, float] = {d: 100.0 for d in drone_ids}
    # Phase 21: drone-level health metadata.  Mutated when a
    # maintenance_completed event fires; persisted to the drones row at
    # end of run so analytics can query battery_health_pct trends.
    drone_health: dict[str, float] = {d: 100.0 for d in drone_ids}
    drone_cycles: dict[str, int]   = {d: 0     for d in drone_ids}

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
            # Phase 21: each completed maintenance cycle = +1 cycle count
            # and ~0.3% health decay (Li-Ion cycle-life ballpark).
            drone_cycles[did] += 1
            drone_health[did]  = max(50.0, drone_health[did] - 0.3)

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
        trip_maintenance_events = 0    # counted by the post-trip maint block

        store     = rng.choice(STORE_NAMES)
        depot_pt  = (DEPOT_LAT, DEPOT_LON)

        # ── distance-driven coordinate generation (Phase 14) ────────────────
        # Pickup and dropoff are drawn around the depot with a radius scaled
        # to the scenario's avg_trip_distance_km, so urban scenarios produce
        # short trips and rural scenarios produce long ones.  RNG draws per
        # point stay at 2 (radius_frac + bearing), preserving the seeded
        # sequence's *length*.
        target_radius = sc.avg_trip_distance_km / _DISTANCE_RADIUS_DIVISOR
        pickup   = _random_point_around(rng, depot_pt, target_radius)
        dropoff  = _random_point_around(rng, depot_pt, target_radius)
        # Pre-compute leg distances now — used for telemetry density,
        # maintenance load coupling, and economics.
        d_leg1   = _haversine_km(depot_pt, pickup)
        d_leg2_normal = _haversine_km(pickup, dropoff)
        d_leg2_abort  = _haversine_km(pickup, depot_pt)
        d_leg3   = _haversine_km(dropoff, depot_pt)

        # ── Phase 19/20: synthetic order characteristics ───────────────────
        # The simulator emits the *intrinsic* per-order traits (payload,
        # urgency, premium flag, congestion, queue pressure).  Activation
        # decisions and latency/cost estimates are now computed downstream
        # by ``transforms/hybrid.py``.  This is the Phase 20 boundary:
        # operational facts here, analytical derivations there.
        chars = generate_order_characteristics(seed, trip_idx, n_trips)

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
                run_id=run_id,
                scenario_name=sc.name,
                payload_weight_kg=chars.payload_weight_kg,
                urgency_level=chars.urgency_level,
                estimated_prep_time_min=chars.estimated_prep_time_min,
                promised_delivery_window_min=chars.promised_delivery_window_min,
                premium_delivery=chars.premium_delivery,
                congestion_factor=chars.congestion_factor,
                queue_pressure=chars.queue_pressure,
                # Phase 20: fulfillment_mode / activation_reason / latency /
                # truck_baseline_* are populated by `transforms/hybrid.py`,
                # not at simulator-write time.  They stay NULL here.
            )
            _insert_trip_row(cur, trip_id=trip_id, drone_id=drone_id,
                             order_id=order_id, depot_id=depot_id,
                             scenario_name=sc.name, run_id=run_id)
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

        # Phase 21: telemetry pings now carry a side-table observation with
        # altitude / airspeed / heading / temps / signal quality / etc.
        ping_steps = _telemetry_steps(rng, d_leg1, sc)
        leg1_bearing = bearing_deg(depot_pt, pickup)
        leg1_seconds = 0.0
        for i, (lat, lon) in enumerate(_interpolate(depot_pt, pickup, ping_steps)):
            battery = max(0.0, battery - rng.uniform(1.5, 3.0) * sc.battery_drain_multiplier)
            dt = rng.randint(20, 45)
            leg1_seconds += dt
            phase = (PHASE_ASCEND if i == 0
                     else (PHASE_DESCEND if i == ping_steps - 1
                           else PHASE_CRUISE))
            ping_id = _emit(
                EVT_TELEMETRY_PING, drone_id=drone_id, trip_id=trip_id, leg_id=leg1_id,
                lat=lat, lon=lon, battery=battery,
                dt_seconds=dt,
            )
            obs = generate_observation(
                rng, phase=phase, payload_kg=chars.payload_weight_kg,
                leg_seconds_so_far=leg1_seconds, bearing_deg=leg1_bearing,
                battery_pct=battery,
                battery_health_pct=drone_health.get(drone_id, 100.0),
                drone_range_km=DRONE_RANGE_KM,
                distance_to_depot_km=_haversine_km((lat, lon), depot_pt),
            )
            _insert_obs(ping_id, obs)
            _maybe_inject_warnings(_emit, rng, sc, drone_id, trip_id, leg1_id, lat, lon, battery)

        _emit(
            EVT_PICKUP_COMPLETED, drone_id=drone_id, trip_id=trip_id, leg_id=leg1_id,
            lat=pickup[0], lon=pickup[1], battery=battery,
            payload={"store_name": store, "order_id": order_id},
            dt_seconds=10,
        )

        # ── leg 2: pickup → dropoff, with telemetry ─────────────────────────
        # Two emergency-return triggers:
        #   * legacy scenario probability roll (RNG) — pre-decides routing
        #   * Phase 21: the on-board flight controller's own remaining-range
        #     check can interrupt mid-leg if its estimate falls below the
        #     distance back to depot * REMAINING_RANGE_SAFETY_FACTOR.
        legacy_emergency = rng.random() < sc.emergency_return_chance
        leg2_distance = d_leg2_abort if legacy_emergency else d_leg2_normal
        ping_steps = _telemetry_steps(rng, leg2_distance, sc)
        end_point = depot_pt if legacy_emergency else dropoff

        emergency = legacy_emergency
        # Reason strings include a keyword from the projection's
        # ``needs_service`` filter (battery / fault / obstacle) so the drone
        # is routed through maintenance, not back to idle.
        emergency_reason = "obstacle_or_unknown_fault" if legacy_emergency else None
        leg2_bearing = bearing_deg(pickup, end_point)
        leg2_seconds = 0.0
        for i, (lat, lon) in enumerate(_interpolate(pickup, end_point, ping_steps)):
            battery = max(0.0, battery - rng.uniform(2.0, 4.0) * sc.battery_drain_multiplier)
            dt = rng.randint(20, 45)
            leg2_seconds += dt
            ping_id = _emit(
                EVT_TELEMETRY_PING, drone_id=drone_id, trip_id=trip_id, leg_id=leg2_id,
                lat=lat, lon=lon, battery=battery,
                dt_seconds=dt,
            )
            obs = generate_observation(
                rng, phase=PHASE_CRUISE, payload_kg=chars.payload_weight_kg,
                leg_seconds_so_far=leg2_seconds, bearing_deg=leg2_bearing,
                battery_pct=battery,
                battery_health_pct=drone_health.get(drone_id, 100.0),
                drone_range_km=DRONE_RANGE_KM,
                distance_to_depot_km=_haversine_km((lat, lon), depot_pt),
            )
            _insert_obs(ping_id, obs)
            _maybe_inject_warnings(_emit, rng, sc, drone_id, trip_id, leg2_id, lat, lon, battery)
            # Phase 21: onboard controller can trigger emergency if its own
            # remaining-range estimate doesn't cover the trip home.
            if not emergency and remaining_range_triggers_emergency(
                obs, _haversine_km((lat, lon), depot_pt),
            ):
                emergency = True
                # "battery" keyword tells the emergency_return projection to
                # route the drone through maintenance (low battery is the
                # *cause* of the low remaining-range estimate).
                emergency_reason = "onboard_remaining_range_low_battery"
                break

        if emergency:
            _emit(
                EVT_EMERGENCY_RETURN, drone_id=drone_id, trip_id=trip_id, leg_id=leg2_id,
                lat=depot_pt[0], lon=depot_pt[1], battery=battery,
                payload={"reason": emergency_reason or "low_battery_or_obstacle",
                         "order_id": order_id},
                dt_seconds=5,
            )
            drone_battery[drone_id] = battery
            # Emergency-return drones always go through maintenance before
            # returning to service — matches the projection logic that already
            # transitions the drone to MAINTENANCE on this event.
            schedule_maintenance(drone_id, "post_emergency_return")
            trip_maintenance_events += 1
        else:
            _emit(
                EVT_DELIVERY_COMPLETED, drone_id=drone_id, trip_id=trip_id, leg_id=leg2_id,
                lat=dropoff[0], lon=dropoff[1], battery=battery,
                payload={"order_id": order_id, "store_name": store},
                dt_seconds=10,
            )
            # ── leg 3: dropoff → depot, with telemetry ──────────────────────
            return_steps = _telemetry_steps(rng, d_leg3, sc)
            leg3_bearing = bearing_deg(dropoff, depot_pt)
            leg3_seconds = 0.0
            for i, (lat, lon) in enumerate(_interpolate(dropoff, depot_pt, return_steps)):
                battery = max(0.0, battery - rng.uniform(1.5, 3.0) * sc.battery_drain_multiplier)
                dt = rng.randint(20, 45)
                leg3_seconds += dt
                phase = (PHASE_DESCEND if i == return_steps - 1 else PHASE_CRUISE)
                ping_id = _emit(
                    EVT_TELEMETRY_PING, drone_id=drone_id, trip_id=trip_id, leg_id=leg3_id,
                    lat=lat, lon=lon, battery=battery,
                    dt_seconds=dt,
                )
                obs = generate_observation(
                    rng, phase=phase, payload_kg=0.0,   # parcel delivered
                    leg_seconds_so_far=leg3_seconds, bearing_deg=leg3_bearing,
                    battery_pct=battery,
                    battery_health_pct=drone_health.get(drone_id, 100.0),
                    drone_range_km=DRONE_RANGE_KM,
                    distance_to_depot_km=_haversine_km((lat, lon), depot_pt),
                )
                _insert_obs(ping_id, obs)
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
        # Maintenance probability now has THREE contributors:
        #   - the scenario's baseline maintenance_chance (probability knob),
        #   - a low-battery bump if the drone finished near empty,
        #   - a long-trip bump if the trip ran 1.5x its scenario's avg dist.
        # The RNG is drawn unconditionally so the seeded sequence is stable
        # even when the load factors push the effective chance above 1.0.
        maint_roll = rng.random()
        trip_distance_km = d_leg1 + leg2_distance + (0.0 if emergency else d_leg3)
        low_battery_factor = 0.10 if drone_battery[drone_id] < 30 else 0.0
        distance_factor = (
            0.05 if trip_distance_km > sc.avg_trip_distance_km * 1.5 else 0.0
        )
        effective_chance = sc.maintenance_chance + low_battery_factor + distance_factor
        if drone_battery[drone_id] < 25 or maint_roll < effective_chance:
            if drone_status[drone_id] == "idle":
                if drone_battery[drone_id] < 25:
                    reason = "low_battery"
                elif low_battery_factor or distance_factor:
                    reason = "operational_stress"
                else:
                    reason = "scheduled_inspection"
                _emit(
                    EVT_MAINTENANCE_REQUIRED,
                    drone_id=drone_id,
                    trip_id=trip_id,  # Phase 20: attribute to the just-completed trip
                    payload={
                        "reason":              reason,
                        "trip_distance_km":    round(trip_distance_km, 2),
                        "end_battery_pct":     round(drone_battery[drone_id], 2),
                        "effective_chance":    round(effective_chance, 4),
                    },
                    dt_seconds=30,
                )
                schedule_maintenance(drone_id, reason)
                trip_maintenance_events += 1
            # If the drone is already in maintenance (e.g. after an emergency
            # return), don't re-emit the request — the existing completion
            # event already covers it.

        # Phase 20: trip economics (cost / profit / revenue / distance) are
        # now derived by `transforms/economics.py` after the run completes.
        # The simulator does not write to those columns here.

    # Phase 21: persist drone-level health metadata back into the drones
    # row.  These are slowly-changing values (not per-ping telemetry).
    conn = sqlite3.connect(db_path)
    try:
        for did in drone_ids:
            conn.execute(
                "UPDATE drones SET battery_cycle_count = ?, "
                "                  battery_health_pct  = ? "
                " WHERE drone_id = ?",
                (drone_cycles[did], round(drone_health[did], 2), did),
            )
        events_written = conn.execute(
            "SELECT COUNT(*) FROM delivery_events"
        ).fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    # Trim zero-count keys for a cleaner summary.
    event_counts_by_type = {k: v for k, v in counts.items() if v > 0}

    # Phase 20: auto-run the transform pipeline so derived columns
    # (estimated_profit, fulfillment_mode, etc.) are populated before the
    # caller queries them.  CLIs and direct callers can opt out via
    # ``run_transforms=False`` if they want to inspect raw simulator state.
    if run_transforms:
        # Local import to avoid an apparent circular dependency at module
        # load — transforms.* imports from core.* but not from core.simulator.
        from transforms.runner import run_pipeline
        run_pipeline(db_path, run_id=run_id)

    return {
        "drones":               len(drone_ids),
        "trips_requested":      n_trips,
        "trips_completed":      trips_completed,
        "events_written":       events_written,
        "event_counts_by_type": event_counts_by_type,
        "db_path":              db_path,
        "scenario":             sc.name,
        "run_id":               run_id,
        "assumption_version":   ASSUMPTION_VERSION,
        "simulator_version":    SIMULATOR_VERSION,
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
    # Phase 21: rare obstacle detection.  A separate event type (not a
    # telemetry-payload flag) since this is a discrete observation, not a
    # continuous reading.
    if rng.random() < OBSTACLE_WARNING_BASE_PROB:
        emit_fn(
            EVT_OBSTACLE_WARNING, drone_id=drone_id, trip_id=trip_id, leg_id=leg_id,
            lat=lat, lon=lon, battery=battery,
            payload={
                "detected_distance_m": round(rng.uniform(5.0, 60.0), 1),
                "action_taken":        "altitude_increase",
            },
            dt_seconds=1,
        )
