"""Deterministic simulation + emergency_return projection checks.

The seed=42 scenario happens to produce exactly one emergency_return,
so the projection assertions piggyback on it instead of constructing
a controlled scenario from raw emit() calls.  That keeps the test set
small and exercises the real call path that production code uses.
"""

import sqlite3
from pathlib import Path

# Expected outcomes for run_simulation(n_drones=3, n_trips=10, seed=42).
SEED42_EVENTS_WRITTEN  = 172
SEED42_TRIPS_REQUESTED = 10
SEED42_TRIPS_COMPLETED = 9


EXPECTED_OPERATIONAL_EVENT_TYPES = {
    "order_created", "drone_assigned", "drone_launched",
    "telemetry_ping", "pickup_completed", "delivery_completed",
    "battery_warning", "route_deviation",
    "emergency_return", "maintenance_required",
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
    assert counts.get("delivered") == 9
    assert counts.get("error")     == 1


def test_seed42_trip_outcomes(seed42_db: Path):
    conn = sqlite3.connect(str(seed42_db))
    try:
        counts = dict(conn.execute(
            "SELECT status, COUNT(*) FROM trips GROUP BY status"
        ).fetchall())
    finally:
        conn.close()
    assert counts.get("completed") == 9
    assert counts.get("aborted")   == 1


def test_no_drone_left_flying(seed42_db: Path):
    conn = sqlite3.connect(str(seed42_db))
    try:
        flying = conn.execute(
            "SELECT COUNT(*) FROM drones WHERE status = 'flying'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert flying == 0


def test_emergency_return_projections(seed42_db: Path):
    """Order → error, trip → aborted, drone is no longer flying."""
    conn = sqlite3.connect(str(seed42_db))
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
