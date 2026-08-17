"""Deterministic simulation + projection checks.

Phase 21 update: at seed=42 the new per-ping telemetry RNG draws shifted
the seeded sequence enough that the legacy ``emergency_return`` probability
now fires once (one trip aborts instead of all 10 completing).  Tests
updated to expect 9 completed + 1 aborted; the trailing-open maintenance
case is no longer expected because the new reason strings route the drone
through maintenance correctly.
"""

import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from baselines import expected_events  # noqa: E402


# Expected outcomes for run_simulation(n_drones=3, n_trips=10, seed=42)
# under the *current* simulator version.  Sourced from tests/baselines.py
# so a bump only requires one edit there.
SEED42_EVENTS_WRITTEN  = expected_events(seed=42)
SEED42_TRIPS_REQUESTED = 10
# Phase 21: legacy emergency_return probability now fires once at seed=42
# because telemetry RNG draws shifted the sequence (see baselines.py).
SEED42_TRIPS_COMPLETED = 9


EXPECTED_OPERATIONAL_EVENT_TYPES = {
    "order_created", "drone_assigned", "drone_launched",
    "telemetry_ping", "pickup_completed", "delivery_completed",
    "returned_to_depot",
    "battery_warning", "route_deviation",
    "maintenance_required", "maintenance_completed",
    "emergency_return",   # Phase 21: now fires at seed=42 too
}


def test_seed42_counts(seed42_summary: dict):
    assert seed42_summary["events_written"]  == SEED42_EVENTS_WRITTEN
    assert seed42_summary["trips_requested"] == SEED42_TRIPS_REQUESTED
    assert seed42_summary["trips_completed"] == SEED42_TRIPS_COMPLETED


def test_seed42_event_vocabulary(seed42_summary: dict):
    present = set(seed42_summary["event_counts_by_type"].keys())
    missing = EXPECTED_OPERATIONAL_EVENT_TYPES - present
    assert not missing, f"event types absent from seed=42 run: {missing}"


def test_seed42_order_outcomes(seed42_db: Path):
    conn = sqlite3.connect(str(seed42_db))
    try:
        counts = dict(conn.execute(
            "SELECT status, COUNT(*) FROM orders GROUP BY status"
        ).fetchall())
    finally:
        conn.close()
    # Phase 21: one emergency_return at seed=42 → 9 delivered + 1 error.
    assert counts.get("delivered")  == 9
    assert counts.get("error",  0)  == 1


def test_seed42_trip_outcomes(seed42_db: Path):
    conn = sqlite3.connect(str(seed42_db))
    try:
        counts = dict(conn.execute(
            "SELECT status, COUNT(*) FROM trips GROUP BY status"
        ).fetchall())
    finally:
        conn.close()
    # Phase 21: one emergency_return at seed=42 → 9 completed + 1 aborted.
    assert counts.get("completed")   == 9
    assert counts.get("aborted", 0)  == 1


def test_no_drone_left_flying(seed42_db: Path):
    conn = sqlite3.connect(str(seed42_db))
    try:
        flying = conn.execute(
            "SELECT COUNT(*) FROM drones WHERE status = 'flying'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert flying == 0


# ─────────────────────────────────────────────────────────────────────────────
# Return-to-depot leg modeling
# ─────────────────────────────────────────────────────────────────────────────

def test_completed_trips_have_returned_to_depot_event(seed42_db: Path):
    """Every completed trip has exactly one returned_to_depot event."""
    conn = sqlite3.connect(str(seed42_db))
    try:
        rows = conn.execute("""
            SELECT t.trip_id,
                   (SELECT COUNT(*) FROM delivery_events e
                     WHERE e.trip_id    = t.trip_id
                       AND e.event_type = 'returned_to_depot') AS n
              FROM trips t
             WHERE t.status = 'completed'
        """).fetchall()
    finally:
        conn.close()
    assert rows, "expected at least one completed trip"
    missing = [tid for tid, n in rows if n != 1]
    assert not missing, f"completed trips without returned_to_depot: {missing}"


def test_completed_trips_have_three_completed_legs(seed42_db: Path):
    """Trip projection counts pickup + delivery + return = 3 legs."""
    conn = sqlite3.connect(str(seed42_db))
    try:
        rows = conn.execute(
            "SELECT trip_id, legs_completed FROM trips WHERE status = 'completed'"
        ).fetchall()
    finally:
        conn.close()
    wrong = [(tid, n) for tid, n in rows if n != 3]
    assert not wrong, f"completed trips with legs_completed != 3: {wrong}"


def test_drone_remains_active_between_delivery_and_return(seed42_db: Path):
    """For each delivery_completed there must be no idle-marking event for
    that drone until the matching returned_to_depot fires."""
    conn = sqlite3.connect(str(seed42_db))
    try:
        rows = conn.execute(
            "SELECT trip_id, drone_id, event_time, event_type "
            "  FROM delivery_events "
            " WHERE drone_id IS NOT NULL "
            "   AND event_type IN ('delivery_completed', 'returned_to_depot', "
            "                      'drone_assigned', 'maintenance_completed') "
            " ORDER BY drone_id, event_time, event_id"
        ).fetchall()
    finally:
        conn.close()

    pending_return: dict[str, str] = {}  # drone_id -> trip_id we're waiting on
    for trip_id, drone_id, _ts, etype in rows:
        if etype == "delivery_completed":
            assert drone_id not in pending_return, (
                f"{drone_id} had a second delivery_completed before returning"
            )
            pending_return[drone_id] = trip_id
        elif etype == "returned_to_depot":
            assert pending_return.pop(drone_id, None) == trip_id, (
                f"returned_to_depot for {drone_id}/{trip_id} without prior "
                f"delivery_completed"
            )
        elif etype in ("drone_assigned", "maintenance_completed"):
            assert drone_id not in pending_return, (
                f"{drone_id} got {etype} while still mid-return for "
                f"{pending_return[drone_id]}"
            )
    assert not pending_return, f"deliveries without returns: {pending_return}"


def test_maintenance_gates_dispatch(seed42_db: Path):
    """Per-drone replay: no drone_assigned ever fires while in maintenance.

    Also asserts every maintenance opening event (maintenance_required or
    emergency_return) is eventually closed out by a maintenance_completed.
    """
    conn = sqlite3.connect(str(seed42_db))
    try:
        rows = conn.execute(
            "SELECT drone_id, event_time, event_type FROM delivery_events "
            "WHERE drone_id IS NOT NULL "
            "ORDER BY drone_id ASC, event_time ASC, event_id ASC"
        ).fetchall()
    finally:
        conn.close()

    state: dict[str, str] = {}
    open_maintenance: dict[str, int] = {}
    for drone_id, _ts, etype in rows:
        cur = state.get(drone_id, "idle")
        if etype == "drone_assigned":
            assert cur != "maintenance", (
                f"{drone_id} was assigned while in maintenance"
            )
            state[drone_id] = "assigned"
        elif etype in ("drone_launched", "pickup_completed",
                       "telemetry_ping", "delivery_completed"):
            state[drone_id] = "flying"
        elif etype in ("returned_to_depot", "maintenance_completed"):
            state[drone_id] = "idle"
            if etype == "maintenance_completed":
                open_maintenance[drone_id] = open_maintenance.get(drone_id, 0) - 1
        elif etype == "maintenance_required":
            state[drone_id] = "maintenance"
            open_maintenance[drone_id] = open_maintenance.get(drone_id, 0) + 1
        elif etype == "emergency_return":
            state[drone_id] = "maintenance"
            open_maintenance[drone_id] = open_maintenance.get(drone_id, 0) + 1

    # A trailing unmatched maintenance is acceptable iff that drone's
    # projection actually still shows it as in-maintenance at sim end.
    conn = sqlite3.connect(str(seed42_db))
    try:
        still_in_maint = {r[0] for r in conn.execute(
            "SELECT drone_id FROM drones WHERE status = 'maintenance'"
        ).fetchall()}
    finally:
        conn.close()
    leftover = {k: v for k, v in open_maintenance.items()
                if not (v == 0 or (v == 1 and k in still_in_maint))}
    assert not leftover, f"unmatched maintenance events: {leftover}"


def test_emergency_return_projections(emergency_db: Path):
    """Order → error, trip → aborted, drone is no longer flying.

    Uses the seed=1 fixture; seed=42 no longer produces an emergency_return
    after Phase 8's RNG drift.
    """
    conn = sqlite3.connect(str(emergency_db))
    try:
        emergencies = conn.execute(
            "SELECT trip_id, drone_id FROM delivery_events "
            "WHERE event_type = 'emergency_return'"
        ).fetchall()
        assert emergencies, "expected at least one emergency_return event"

        for trip_id, drone_id in emergencies:
            trip_row = conn.execute(
                "SELECT status, order_id FROM trips WHERE trip_id = ?",
                (trip_id,),
            ).fetchone()
            assert trip_row is not None
            trip_status, order_id = trip_row
            assert trip_status == "aborted"

            order_status = conn.execute(
                "SELECT status FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()[0]
            assert order_status == "error"

            drone_status = conn.execute(
                "SELECT status FROM drones WHERE drone_id = ?",
                (drone_id,),
            ).fetchone()[0]
            assert drone_status != "flying"
    finally:
        conn.close()
