"""Phase 14: avg_trip_distance_km materially drives simulator output.

These tests verify that the operational-environment knobs *cause* observed
behaviour, not just label it.  They share the session-scoped
``multi_scenario_db`` fixture from conftest.py (3 scenarios × 100 trips);
every consumer is marked ``@pytest.mark.slow``.
"""

import sqlite3
from pathlib import Path

import pytest

from core.scenarios import get_scenario
from core.simulator import run_simulation

# multi_scenario_db fixture is provided by conftest.py (session-scoped).


def _observed_avg_distance(db: Path) -> dict[str, float]:
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT scenario_name, AVG(trip_distance_km) "
            "  FROM trips WHERE scenario_name IS NOT NULL "
            " GROUP BY scenario_name"
        ).fetchall()
    finally:
        conn.close()
    return {s: float(d) for s, d in rows}


def _telemetry_per_trip(db: Path) -> dict[str, float]:
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            """
            SELECT t.scenario_name,
                   1.0 * SUM(CASE WHEN e.event_type='telemetry_ping' THEN 1 ELSE 0 END)
                       / COUNT(DISTINCT t.trip_id)
              FROM trips t
              LEFT JOIN delivery_events e ON e.trip_id = t.trip_id
             WHERE t.scenario_name IS NOT NULL
             GROUP BY t.scenario_name
            """
        ).fetchall()
    finally:
        conn.close()
    return {s: float(v or 0) for s, v in rows}


@pytest.mark.slow
def test_observed_distance_ordering(multi_scenario_db: Path):
    """rural avg trip distance > suburban > urban (the whole point of Phase 14)."""
    obs = _observed_avg_distance(multi_scenario_db)
    assert obs["rural_extended"]    > obs["suburban_standard"]
    assert obs["suburban_standard"] > obs["urban_dense"]


@pytest.mark.slow
def test_observed_distance_tracks_configured(multi_scenario_db: Path):
    """Observed avg should land within 2 km of the configured target.

    Tolerance is wide enough to absorb the polar-geometry variance
    (pickup/dropoff bearings are independent) and still small enough
    to be a real assertion.
    """
    obs = _observed_avg_distance(multi_scenario_db)
    for name, expected in (("urban_dense",       3.0),
                           ("suburban_standard", 6.0),
                           ("rural_extended",   12.0)):
        cfg = get_scenario(name).avg_trip_distance_km
        assert cfg == expected   # sanity
        assert abs(obs[name] - cfg) <= 2.0, (
            f"{name}: observed {obs[name]:.2f} km vs configured {cfg} km "
            f"(drift > 2 km tolerance)"
        )


@pytest.mark.slow
def test_telemetry_scales_with_distance(multi_scenario_db: Path):
    """Per-trip telemetry pings should rise materially from suburban → rural.

    Note: urban_dense gets a +2 telemetry_bonus_per_leg, which intentionally
    overcomes its short legs — so urban can carry MORE pings per trip than
    suburban.  That's a feature, not a bug: it's the "dense city telemetry"
    knob doing its job.  Rural legs are still long enough to outweigh the
    urban bonus, so rural > urban must hold.
    """
    pings = _telemetry_per_trip(multi_scenario_db)
    assert pings["rural_extended"] > pings["urban_dense"], (
        f"rural pings/trip {pings['rural_extended']:.1f} should exceed "
        f"urban {pings['urban_dense']:.1f}"
    )
    assert pings["rural_extended"] > pings["suburban_standard"], (
        f"rural pings/trip {pings['rural_extended']:.1f} should exceed "
        f"suburban {pings['suburban_standard']:.1f}"
    )


@pytest.mark.slow
def test_maintenance_differs_by_scenario(multi_scenario_db: Path):
    """Rural's load coupling should push its maintenance rate above urban's.

    Maintenance events fire BETWEEN trips, so ``delivery_events.trip_id``
    is NULL on them; they have to be grouped via ``scenario_name`` directly
    and divided by the per-scenario trip count from ``trips``.
    """
    conn = sqlite3.connect(str(multi_scenario_db))
    try:
        trip_counts = dict(conn.execute(
            "SELECT scenario_name, COUNT(*) FROM trips "
            "WHERE scenario_name IS NOT NULL GROUP BY scenario_name"
        ).fetchall())
        maint_counts = dict(conn.execute(
            "SELECT scenario_name, COUNT(*) FROM delivery_events "
            "WHERE event_type='maintenance_required' AND scenario_name IS NOT NULL "
            "GROUP BY scenario_name"
        ).fetchall())
    finally:
        conn.close()
    rates = {s: maint_counts.get(s, 0) / trip_counts[s] for s in trip_counts}
    assert rates["rural_extended"] > rates["urban_dense"], (
        f"rural maint/trip {rates['rural_extended']:.3f} should exceed "
        f"urban {rates['urban_dense']:.3f} under distance-driven load"
    )


def test_same_seed_same_scenario_deterministic(tmp_path: Path):
    """Phase 14 changes must not break determinism — same seed + scenario twice
    yields identical event totals and per-type counts."""
    a = run_simulation(db_path=str(tmp_path / "a.sqlite"),
                       n_drones=3, n_trips=20, seed=42, scenario="rural_extended")
    b = run_simulation(db_path=str(tmp_path / "b.sqlite"),
                       n_drones=3, n_trips=20, seed=42, scenario="rural_extended")
    assert a["events_written"]       == b["events_written"]
    assert a["event_counts_by_type"] == b["event_counts_by_type"]
