"""Calibration drift: metrics, drift math, SQL, chart, CLI."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from core.calibration import (
    ALIGN_KM, ALIGN_PROB, DIVERGE_KM, DIVERGE_PROB,
    compute_calibration_drift, compute_observed_metrics,
    generate_calibration_interpretations, generate_calibration_summary,
)

# multi_scenario_db fixture is provided by conftest.py (session-scoped).
# All tests in this file that depend on it are marked @pytest.mark.slow so
# that ``pytest -m "not slow"`` skips them and the expensive DB build.


@pytest.mark.slow
def test_observed_metrics_non_empty(multi_scenario_db: Path):
    rows = compute_observed_metrics(str(multi_scenario_db))
    assert rows
    seen = {r["scenario_name"] for r in rows}
    assert seen == {"urban_dense", "suburban_standard", "rural_extended"}


@pytest.mark.slow
def test_observed_rates_bounded_in_unit_interval(multi_scenario_db: Path):
    for r in compute_observed_metrics(str(multi_scenario_db)):
        for k in ("completion_rate",
                  "observed_emergency_return_rate",
                  "observed_maintenance_rate",
                  "observed_battery_warning_rate",
                  "observed_route_deviation_rate"):
            assert 0.0 <= r[k] <= 1.0, f"{r['scenario_name']}.{k} = {r[k]} out of [0,1]"


@pytest.mark.slow
def test_drift_calculations_deterministic(multi_scenario_db: Path):
    a = compute_calibration_drift(str(multi_scenario_db))
    b = compute_calibration_drift(str(multi_scenario_db))
    assert a == b


@pytest.mark.slow
def test_drift_equals_observed_minus_configured(multi_scenario_db: Path):
    for r in compute_calibration_drift(str(multi_scenario_db)):
        assert round(
            r["observed_emergency_return_rate"]
            - r["configured_emergency_return_chance"], 4
        ) == r["emergency_return_drift"]
        assert round(
            r["observed_maintenance_rate"]
            - r["configured_maintenance_chance"], 4
        ) == r["maintenance_drift"]


@pytest.mark.slow
def test_at_least_one_scenario_shows_non_zero_drift(multi_scenario_db: Path):
    rows = compute_calibration_drift(str(multi_scenario_db))
    assert any(
        abs(r["emergency_return_drift"]) > 0
        or abs(r["maintenance_drift"]) > 0
        or abs(r["route_deviation_drift"]) > 0
        or abs(r["avg_trip_distance_drift_km"]) > 0
        for r in rows
    )


def test_threshold_constants_ordering():
    assert 0 < ALIGN_PROB < DIVERGE_PROB
    assert 0 < ALIGN_KM   < DIVERGE_KM


@pytest.mark.slow
def test_interpretations_non_empty(multi_scenario_db: Path):
    bullets = generate_calibration_interpretations(str(multi_scenario_db))
    assert bullets
    assert all(isinstance(b, str) and b.strip() for b in bullets)


@pytest.mark.slow
def test_summary_bundles_everything(multi_scenario_db: Path):
    s = generate_calibration_summary(str(multi_scenario_db))
    for k in ("drift_rows", "interpretations", "thresholds"):
        assert k in s
    assert s["thresholds"]["ALIGN_PROB"] == ALIGN_PROB


@pytest.mark.slow
def test_calibration_sql_runs(multi_scenario_db: Path):
    sql = Path("analytics/sql/calibration_drift.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(multi_scenario_db))
    try:
        rows    = conn.execute(sql).fetchall()
        headers = [d[0] for d in conn.execute(sql).description]
    finally:
        conn.close()
    assert rows
    for col in ("cfg_emergency_return_chance", "observed_emergency_return_rate",
                "emergency_return_drift",      "maintenance_drift",
                "route_deviation_drift",       "avg_trip_distance_drift_km"):
        assert col in headers, f"missing column: {col}"


@pytest.mark.slow
def test_calibration_chart_renders(multi_scenario_db: Path, tmp_path: Path):
    from core.visualizations import generate_charts
    paths = generate_charts(db_path=str(multi_scenario_db), out_dir=str(tmp_path / "charts"))
    p = Path(paths["scenario_calibration_drift"])
    assert p.exists()
    assert p.stat().st_size > 0


@pytest.mark.slow
def test_calibration_cli_writes_markdown(multi_scenario_db: Path, tmp_path: Path):
    out = tmp_path / "rep.md"
    res = subprocess.run(
        [sys.executable, "run_calibration_analysis.py",
         "--db", str(multi_scenario_db), "--markdown", str(out)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert res.returncode == 0, res.stderr
    assert out.exists() and out.stat().st_size > 0
    text = out.read_text(encoding="utf-8")
    assert "Calibration"  in text or "calibration" in text
    assert "Interpretations" in text
    assert "urban_dense"  in text
