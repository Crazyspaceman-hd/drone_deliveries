"""Phase 21: telemetry enrichment.

Tests focus on the source/transform separation:
  * simulator emits ``telemetry_observations`` rows and an
    ``obstacle_warning`` event type;
  * values sit inside the public-source plausibility bands;
  * the telemetry transform derives summaries + anomaly counts;
  * the onboard remaining-range emergency trigger fires when the
    onboard estimate drops below the depot distance × safety factor.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

# telemetry_db fixture is provided by conftest.py (session-scoped).

# Pin the value-range bands.  Bumps to the simulator's plausibility envelope
# should land in core/telemetry_model.py and be reflected here.
_BANDS = {
    "altitude_m":          (0.0,  120.0),
    "airspeed_mps":        (0.0,   35.0),
    "heading_deg":         (0.0,  360.0),
    "vertical_speed_mps":  (-5.5,   5.5),
    "battery_temp_c":      (10.0,  65.0),
    "motor_temp_c":        (15.0,  100.0),
    "signal_strength_pct": (40.0,  100.0),
    "gps_signal_quality":  (30.0,  100.0),
}


# ─────────────────────────────────────────────────────────────────────────────
# Source-layer observable presence + sanity
# ─────────────────────────────────────────────────────────────────────────────

def test_every_telemetry_ping_has_an_observation(telemetry_db: Path):
    conn = sqlite3.connect(str(telemetry_db))
    try:
        pings = conn.execute(
            "SELECT COUNT(*) FROM delivery_events WHERE event_type='telemetry_ping'"
        ).fetchone()[0]
        obs = conn.execute(
            "SELECT COUNT(*) FROM telemetry_observations"
        ).fetchone()[0]
    finally:
        conn.close()
    assert pings > 0
    assert pings == obs, f"pings={pings} but observations={obs}"


def test_observation_values_within_plausibility_bands(telemetry_db: Path):
    conn = sqlite3.connect(str(telemetry_db))
    try:
        rows = conn.execute(
            "SELECT altitude_m, airspeed_mps, heading_deg, vertical_speed_mps, "
            "       battery_temp_c, motor_temp_c, signal_strength_pct, "
            "       gps_signal_quality FROM telemetry_observations"
        ).fetchall()
    finally:
        conn.close()
    keys = ("altitude_m", "airspeed_mps", "heading_deg", "vertical_speed_mps",
            "battery_temp_c", "motor_temp_c", "signal_strength_pct",
            "gps_signal_quality")
    for row in rows:
        for k, v in zip(keys, row):
            lo, hi = _BANDS[k]
            assert lo <= v <= hi, (
                f"{k}={v} outside plausibility band [{lo}, {hi}]"
            )


def test_obstacle_warning_is_an_event_not_a_flag(telemetry_db: Path):
    """Obstacle warnings live in delivery_events, not in telemetry_observations
    (Phase 21 design — discrete events stay discrete)."""
    conn = sqlite3.connect(str(telemetry_db))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM delivery_events "
            "WHERE event_type = 'obstacle_warning'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n >= 1, "expected at least one obstacle_warning event in the dataset"


def test_drone_health_columns_populated(telemetry_db: Path):
    conn = sqlite3.connect(str(telemetry_db))
    try:
        rows = conn.execute(
            "SELECT drone_id, battery_cycle_count, battery_health_pct FROM drones"
        ).fetchall()
    finally:
        conn.close()
    assert rows
    for did, cycles, health in rows:
        assert cycles is not None
        assert health is not None
        assert 50.0 <= float(health) <= 100.0


def test_battery_health_monotonically_non_increasing(telemetry_db: Path):
    """A drone's battery_health_pct never exceeds 100 and is plausible
    relative to its cycle count.  Concrete invariant: health ≥ 100 − 0.3 × cycles
    minus a small slack for any future jitter."""
    conn = sqlite3.connect(str(telemetry_db))
    try:
        rows = conn.execute(
            "SELECT battery_cycle_count, battery_health_pct FROM drones"
        ).fetchall()
    finally:
        conn.close()
    for cycles, health in rows:
        expected_min = 100.0 - 0.3 * (cycles or 0) - 0.5  # 0.5 slack
        assert float(health) >= max(50.0, expected_min)


# ─────────────────────────────────────────────────────────────────────────────
# Transform layer
# ─────────────────────────────────────────────────────────────────────────────

def test_telemetry_transform_writes_summary_rows(telemetry_db: Path):
    conn = sqlite3.connect(str(telemetry_db))
    try:
        rows = conn.execute(
            "SELECT scenario_name, ping_count, max_battery_temp_c, "
            "       battery_temp_hot_count, obstacle_warning_count "
            "  FROM telemetry_summaries ORDER BY scenario_name ASC"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 2  # one per scenario
    scenarios = {r[0] for r in rows}
    assert scenarios == {"urban_dense", "rural_extended"}
    for _scen, ping_count, _max_t, _hot, _obs in rows:
        assert ping_count > 0


def test_transform_is_discovered_by_runner():
    """Auto-discovery picks up transforms/telemetry.py and orders it last."""
    from transforms.runner import pipeline_names
    names = pipeline_names()
    assert "telemetry" in names
    # Telemetry's RUN_ORDER = 30 → it should be last in the current pipeline.
    assert names[-1] == "telemetry"


def test_transform_is_idempotent(telemetry_db: Path):
    from transforms import telemetry
    telemetry.run(str(telemetry_db))
    conn = sqlite3.connect(str(telemetry_db))
    try:
        before = conn.execute(
            "SELECT scenario_name, avg_battery_temp_c FROM telemetry_summaries "
            " ORDER BY scenario_name"
        ).fetchall()
    finally:
        conn.close()
    telemetry.run(str(telemetry_db))
    conn = sqlite3.connect(str(telemetry_db))
    try:
        after = conn.execute(
            "SELECT scenario_name, avg_battery_temp_c FROM telemetry_summaries "
            " ORDER BY scenario_name"
        ).fetchall()
    finally:
        conn.close()
    assert before == after


# ─────────────────────────────────────────────────────────────────────────────
# Onboard remaining-range emergency trigger
# ─────────────────────────────────────────────────────────────────────────────

def test_remaining_range_helper_decision_boundary():
    """The pure decision function fires iff estimated range < distance × factor."""
    from core.telemetry_model import (
        REMAINING_RANGE_SAFETY_FACTOR, TelemetryObservation,
        remaining_range_triggers_emergency,
    )
    # Build a stub observation that's only used for its remaining-range field.
    def _obs(remaining_km: float) -> TelemetryObservation:
        return TelemetryObservation(
            altitude_m=80, airspeed_mps=14, heading_deg=0,
            vertical_speed_mps=0, battery_temp_c=30, motor_temp_c=40,
            estimated_remaining_range_km=remaining_km,
            signal_strength_pct=90, gps_signal_quality=90,
        )
    # 10 km depot distance, safety factor 1.15 → trigger threshold = 11.5
    assert not remaining_range_triggers_emergency(_obs(20.0), 10.0)
    assert remaining_range_triggers_emergency(_obs(8.0),  10.0)
    # Exact boundary uses strict <
    boundary = 10.0 * REMAINING_RANGE_SAFETY_FACTOR
    assert not remaining_range_triggers_emergency(_obs(boundary), 10.0)


# ─────────────────────────────────────────────────────────────────────────────
# Analytics SQL + API
# ─────────────────────────────────────────────────────────────────────────────

def test_telemetry_summary_sql_executes(telemetry_db: Path):
    sql = Path("analytics/sql/telemetry_summary.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(telemetry_db))
    try:
        rows = conn.execute(sql).fetchall()
        headers = [d[0] for d in conn.execute(sql).description]
    finally:
        conn.close()
    assert rows
    for col in ("scenario_name", "avg_battery_temp_c", "max_motor_temp_c",
                "avg_signal_pct", "avg_remaining_range_km"):
        assert col in headers


@pytest.mark.slow
def test_telemetry_charts_render(telemetry_db: Path, tmp_path: Path):
    from core.visualizations import generate_charts
    paths = generate_charts(db_path=str(telemetry_db),
                            out_dir=str(tmp_path / "charts"))
    for key in ("battery_temperature_by_scenario", "signal_quality_distribution"):
        p = Path(paths[key])
        assert p.exists() and p.stat().st_size > 0


def test_api_telemetry_endpoints(telemetry_db: Path):
    from fastapi.testclient import TestClient
    old = os.environ.get("DRONE_API_DB")
    os.environ["DRONE_API_DB"] = str(telemetry_db)
    try:
        from api.main import app
        client = TestClient(app)
        s = client.get("/analytics/telemetry-summary").json()
        h = client.get("/analytics/telemetry-health").json()
    finally:
        if old is None: del os.environ["DRONE_API_DB"]
        else:           os.environ["DRONE_API_DB"] = old
    assert "by_scenario" in s and s["by_scenario"]
    assert "anomalies_by_scenario" in h
    assert "drone_health" in h
    # Spot-check numeric fields.
    first = s["by_scenario"][0]
    for k in ("avg_battery_temp_c", "avg_motor_temp_c", "avg_signal_pct",
              "avg_remaining_range_km"):
        assert isinstance(first[k], (int, float))
