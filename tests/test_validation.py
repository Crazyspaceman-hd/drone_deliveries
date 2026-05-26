"""Phase 17: rule-based validation framework."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from core.simulator import run_simulation
from core.validation import (
    ERROR, INFO, WARN,
    generate_validation_summary, run_validation_checks, validate_run,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _rule(results: list[dict], name: str) -> dict:
    matches = [r for r in results if r["rule_name"] == name]
    assert matches, f"no rule {name!r} in results"
    return matches[0]


@pytest.fixture(scope="module")
def single_run_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One clean simulation run — should validate fully clean."""
    db = tmp_path_factory.mktemp("val_single") / "x.sqlite"
    run_simulation(db_path=str(db), n_drones=3, n_trips=20, seed=42)
    return db


@pytest.fixture(scope="module")
def multi_run_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three scenarios into one DB."""
    db = tmp_path_factory.mktemp("val_multi") / "x.sqlite"
    for scen in ("urban_dense", "suburban_standard", "rural_extended"):
        run_simulation(db_path=str(db), n_drones=3, n_trips=15,
                       seed=42, scenario=scen)
    return db


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: clean run should pass every ERROR-severity check
# ─────────────────────────────────────────────────────────────────────────────

def test_clean_run_has_no_error_failures(single_run_db: Path):
    results = run_validation_checks(str(single_run_db))
    error_failures = [r for r in results
                      if r["severity"] == ERROR and not r["passed"]]
    assert not error_failures, (
        f"clean run produced ERROR failures: {error_failures}"
    )


def test_summary_shape_and_counts(single_run_db: Path):
    s = generate_validation_summary(str(single_run_db))
    for key in ("results", "counts_by_severity", "failed_by_severity", "any_errors"):
        assert key in s
    assert sum(s["counts_by_severity"].values()) == len(s["results"])
    assert s["failed_by_severity"][ERROR] == 0


def test_validate_run_alias_scopes_to_one_run(multi_run_db: Path):
    conn = sqlite3.connect(str(multi_run_db))
    try:
        rid = conn.execute(
            "SELECT run_id FROM simulation_runs LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()
    results = validate_run(str(multi_run_db), rid)
    # Every result with a run_id field should point at the requested run
    # (the global run_lineage_* checks are skipped when run_id is set).
    rule_names = {r["rule_name"] for r in results}
    assert "run_lineage_delivery_events" not in rule_names


# ─────────────────────────────────────────────────────────────────────────────
# Negative tests: hand-broken DBs should trigger the right failures
# ─────────────────────────────────────────────────────────────────────────────

def test_orphan_run_id_detected(tmp_path: Path):
    db = tmp_path / "orphan.sqlite"
    summ = run_simulation(db_path=str(db), n_drones=3, n_trips=5, seed=42)
    # Plant an orphan: rewrite one event row to point at a run_id that
    # doesn't exist in simulation_runs.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE delivery_events SET run_id = 'orphan-xyz' "
            "WHERE event_id = (SELECT event_id FROM delivery_events LIMIT 1)"
        )
        conn.commit()
    finally:
        conn.close()
    results = run_validation_checks(str(db))
    rule = _rule(results, "run_lineage_delivery_events")
    assert rule["passed"] is False
    assert "orphan-xyz" in rule["affected_rows"]


def test_completed_trip_missing_return_detected(tmp_path: Path):
    db = tmp_path / "missing_return.sqlite"
    summ = run_simulation(db_path=str(db), n_drones=2, n_trips=3, seed=42)
    # Pick one completed trip and remove its returned_to_depot event.
    conn = sqlite3.connect(str(db))
    try:
        trip_id = conn.execute(
            "SELECT trip_id FROM trips WHERE status='completed' LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            "DELETE FROM delivery_events "
            "WHERE trip_id = ? AND event_type = 'returned_to_depot'",
            (trip_id,),
        )
        conn.commit()
    finally:
        conn.close()
    results = run_validation_checks(str(db))
    rule = _rule(results, "completed_trip_has_returned_to_depot")
    assert rule["passed"] is False
    assert rule["severity"] == ERROR
    assert trip_id in rule["affected_rows"]


def test_multi_assignment_detected(tmp_path: Path):
    db = tmp_path / "multi.sqlite"
    run_simulation(db_path=str(db), n_drones=2, n_trips=4, seed=42)
    # Force two trips to share the same drone with overlapping bounds by
    # rewriting drone_id on a second trip's events to match a first one
    # whose flight window we know contains them.
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT trip_id, drone_id FROM trips ORDER BY ROWID LIMIT 2"
        ).fetchall()
        assert len(rows) == 2
        keep_drone = rows[0][1]
        other_trip = rows[1][0]
        # Overwrite the second trip's drone + its event drone_ids to the
        # first trip's drone, with start time inside trip 1's flight window.
        conn.execute(
            "UPDATE trips SET drone_id = ? WHERE trip_id = ?",
            (keep_drone, other_trip),
        )
        conn.execute(
            "UPDATE delivery_events SET drone_id = ? WHERE trip_id = ?",
            (keep_drone, other_trip),
        )
        # Force the second trip's assignment to happen before the first
        # trip ends.
        t1_end = conn.execute(
            "SELECT event_time FROM delivery_events "
            "WHERE trip_id = ? AND event_type IN "
            "      ('returned_to_depot','emergency_return') "
            "ORDER BY event_time DESC LIMIT 1", (rows[0][0],),
        ).fetchone()
        if t1_end is not None:
            # Shift trip 2's drone_assigned to a time strictly before t1_end.
            conn.execute(
                "UPDATE delivery_events SET event_time = "
                "    (SELECT event_time FROM delivery_events "
                "      WHERE trip_id = ? AND event_type = 'drone_assigned') "
                "WHERE trip_id = ? AND event_type = 'drone_assigned'",
                (rows[0][0], other_trip),
            )
        conn.commit()
    finally:
        conn.close()
    results = run_validation_checks(str(db))
    rule = _rule(results, "drone_no_overlapping_trips")
    assert rule["passed"] is False
    assert rule["severity"] == ERROR


def test_negative_distance_triggers_economics_failure(tmp_path: Path):
    db = tmp_path / "neg.sqlite"
    run_simulation(db_path=str(db), n_drones=2, n_trips=3, seed=42)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE trips SET trip_distance_km = -1 "
            "WHERE trip_id = (SELECT trip_id FROM trips "
            "                  WHERE status='completed' LIMIT 1)"
        )
        conn.commit()
    finally:
        conn.close()
    results = run_validation_checks(str(db))
    rule = _rule(results, "economics_finite_and_nonnegative_inputs")
    assert rule["passed"] is False
    assert rule["severity"] == ERROR


def test_parquet_row_mismatch_detected(tmp_path: Path):
    """A truncated parquet file must surface as a WARN parity failure."""
    pyarrow = pytest.importorskip("pyarrow")
    from core.sinks import export_run_to_parquet
    db = tmp_path / "pq.sqlite"
    summ = run_simulation(db_path=str(db), n_drones=2, n_trips=3, seed=42)
    rid = summ["run_id"]
    base = tmp_path / "outputs" / "runs"
    export_run_to_parquet(str(db), rid,
                          out_dir=str(base / f"run_id={rid}" / "parquet"))
    # Drop a row from the parquet so its count diverges from SQLite.
    import pandas as pd
    pq_path = base / f"run_id={rid}" / "parquet" / "delivery_events.parquet"
    df = pd.read_parquet(str(pq_path))
    df.iloc[:-1].to_parquet(str(pq_path), engine="pyarrow", index=False)

    # Patch _check_parquet_export_integrity to look at our tmp base_dir.
    from core import validation as v
    real = v._check_parquet_export_integrity
    def wrapped(conn, run_id, base_dir="outputs/runs"):
        return real(conn, run_id, base_dir=str(base))
    v._check_parquet_export_integrity = wrapped
    try:
        results = run_validation_checks(str(db))
    finally:
        v._check_parquet_export_integrity = real
    parity = [r for r in results if r["rule_name"] == "parquet_row_count_parity"]
    assert any(not r["passed"] and r["severity"] == WARN for r in parity)


# ─────────────────────────────────────────────────────────────────────────────
# SQL + CLI + chart
# ─────────────────────────────────────────────────────────────────────────────

def test_validation_summary_sql_executes(single_run_db: Path):
    sql = Path("analytics/sql/validation_summary.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(single_run_db))
    try:
        rows    = conn.execute(sql).fetchall()
        headers = [d[0] for d in conn.execute(sql).description]
    finally:
        conn.close()
    assert rows
    for col in ("run_id", "scenario", "missing_delivery_completed",
                "missing_returned_to_depot", "legs_completed_violations",
                "maintenance_lifecycle_imbalances", "economic_violations",
                "total_violations"):
        assert col in headers


@pytest.mark.slow
def test_validation_chart_renders(single_run_db: Path, tmp_path: Path):
    from core.visualizations import generate_charts
    paths = generate_charts(db_path=str(single_run_db),
                            out_dir=str(tmp_path / "charts"))
    p = Path(paths["validation_results"])
    assert p.exists() and p.stat().st_size > 0


def test_validation_cli_writes_markdown(single_run_db: Path, tmp_path: Path):
    out = tmp_path / "report.md"
    res = subprocess.run(
        [sys.executable, "run_validation.py",
         "--db", str(single_run_db), "--markdown", str(out)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert res.returncode == 0, res.stderr
    assert out.exists() and out.stat().st_size > 0
    text = out.read_text(encoding="utf-8")
    assert "validation report" in text.lower()
    assert "headline" in text.lower()


def test_validation_cli_exit_codes(tmp_path: Path):
    """Clean DB → exit 0 (no errors).  Missing DB → exit 2."""
    # Clean run.
    db = tmp_path / "clean.sqlite"
    run_simulation(db_path=str(db), n_drones=2, n_trips=3, seed=42)
    res = subprocess.run(
        [sys.executable, "run_validation.py", "--db", str(db)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert res.returncode == 0, res.stdout + res.stderr

    # Missing DB.
    res = subprocess.run(
        [sys.executable, "run_validation.py",
         "--db", str(tmp_path / "no_such.sqlite")],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert res.returncode == 2
