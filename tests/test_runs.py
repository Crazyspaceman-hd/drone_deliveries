"""Phase 15: experiment tracking, lineage, run-aware exports."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from core.runs import (
    ASSUMPTION_VERSION, SIMULATOR_VERSION,
    capture_git_commit, create_simulation_run, get_run, list_runs,
)
from core.simulator import run_simulation


# ─────────────────────────────────────────────────────────────────────────────
# run row creation and lineage
# ─────────────────────────────────────────────────────────────────────────────

def test_run_row_created_per_simulation(tmp_path: Path):
    db = tmp_path / "one.sqlite"
    summ = run_simulation(db_path=str(db), n_drones=3, n_trips=5, seed=42)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT run_id, seed, scenario_names, trip_count, drone_count, "
            "       simulator_version, assumption_version "
            "  FROM simulation_runs"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    rid, seed, scen, trips, drones, sim_v, ass_v = rows[0]
    assert rid                == summ["run_id"]
    assert seed               == 42
    assert scen               == "suburban_standard"
    assert trips              == 5
    assert drones             == 3
    assert sim_v              == SIMULATOR_VERSION
    assert ass_v              == ASSUMPTION_VERSION


def test_events_and_trips_carry_run_id(tmp_path: Path):
    db = tmp_path / "lineage.sqlite"
    summ = run_simulation(db_path=str(db), n_drones=3, n_trips=5, seed=42)
    rid = summ["run_id"]
    conn = sqlite3.connect(str(db))
    try:
        events_with_rid = conn.execute(
            "SELECT COUNT(*) FROM delivery_events WHERE run_id = ?", (rid,)
        ).fetchone()[0]
        events_total = conn.execute(
            "SELECT COUNT(*) FROM delivery_events"
        ).fetchone()[0]
        trips_with_rid = conn.execute(
            "SELECT COUNT(*) FROM trips WHERE run_id = ?", (rid,)
        ).fetchone()[0]
        trips_total = conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
        orders_with_rid = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE run_id = ?", (rid,)
        ).fetchone()[0]
        orders_total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    finally:
        conn.close()
    # Every event/trip/order created by this run carries its run_id.
    assert events_with_rid == events_total > 0
    assert trips_with_rid  == trips_total  > 0
    assert orders_with_rid == orders_total > 0


def test_multi_run_db_has_distinct_rows(tmp_path: Path):
    db = tmp_path / "multi.sqlite"
    for scen in ("urban_dense", "suburban_standard", "rural_extended"):
        run_simulation(db_path=str(db), n_drones=3, n_trips=5, seed=42, scenario=scen)
    conn = sqlite3.connect(str(db))
    try:
        runs   = conn.execute("SELECT COUNT(*) FROM simulation_runs").fetchone()[0]
        scens  = {r[0] for r in conn.execute(
            "SELECT DISTINCT scenario_names FROM simulation_runs"
        ).fetchall()}
    finally:
        conn.close()
    assert runs  == 3
    assert scens == {"urban_dense", "suburban_standard", "rural_extended"}


# ─────────────────────────────────────────────────────────────────────────────
# determinism is preserved
# ─────────────────────────────────────────────────────────────────────────────

def test_determinism_preserved_across_runs(tmp_path: Path):
    """run_id and created_at differ per call, but operational counts don't."""
    a = run_simulation(db_path=str(tmp_path / "a.sqlite"),
                       n_drones=3, n_trips=10, seed=42)
    b = run_simulation(db_path=str(tmp_path / "b.sqlite"),
                       n_drones=3, n_trips=10, seed=42)
    assert a["events_written"]       == b["events_written"]
    assert a["event_counts_by_type"] == b["event_counts_by_type"]
    assert a["run_id"]               != b["run_id"]  # metadata still distinct


# ─────────────────────────────────────────────────────────────────────────────
# git capture
# ─────────────────────────────────────────────────────────────────────────────

def test_git_capture_returns_string_or_none():
    """In a git repo it returns a short hash; outside it returns None.
    Either is acceptable — we just must not raise."""
    val = capture_git_commit()
    assert val is None or (isinstance(val, str) and val.strip())


def test_git_capture_handles_missing_git():
    """If git isn't installed at all the helper must still not raise."""
    with patch("core.runs.subprocess.run", side_effect=FileNotFoundError):
        assert capture_git_commit() is None


def test_git_capture_handles_non_repo():
    """When run inside a directory that isn't a git working tree, returns None."""
    class _FakeResult:
        returncode = 128
        stdout     = ""
        stderr     = "fatal: not a git repository"
    with patch("core.runs.subprocess.run", return_value=_FakeResult):
        assert capture_git_commit() is None


# ─────────────────────────────────────────────────────────────────────────────
# CRUD helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_create_get_list_run(tmp_path: Path):
    db = tmp_path / "x.sqlite"
    # The schema must exist before create_simulation_run.
    from core.setup_db import create_db
    create_db(str(db))

    rid = create_simulation_run(
        str(db), seed=7, scenario_names="urban_dense",
        trip_count=10, drone_count=3, notes="manual test",
        git_commit="",  # explicitly skip capture
    )
    assert isinstance(rid, str) and len(rid) >= 8

    fetched = get_run(str(db), rid)
    assert fetched is not None
    assert fetched["seed"]           == 7
    assert fetched["scenario_names"] == "urban_dense"
    assert fetched["git_commit"]     is None

    listed = list_runs(str(db), limit=5)
    assert rid in {r["run_id"] for r in listed}


# ─────────────────────────────────────────────────────────────────────────────
# analytics SQL + run-aware exports
# ─────────────────────────────────────────────────────────────────────────────

def test_run_summary_sql_runs(tmp_path: Path):
    db = tmp_path / "rs.sqlite"
    for scen in ("urban_dense", "rural_extended"):
        run_simulation(db_path=str(db), n_drones=3, n_trips=5, seed=42, scenario=scen)
    sql = Path("analytics/sql/run_summary.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db))
    try:
        rows    = conn.execute(sql).fetchall()
        headers = [d[0] for d in conn.execute(sql).description]
    finally:
        conn.close()
    assert len(rows) == 2
    for col in ("run_id", "scenarios", "trips", "completed_trips",
                "total_profit", "avg_profit_per_trip",
                "emergency_return_rate", "maintenance_rate"):
        assert col in headers


def test_run_output_dir_helper(tmp_path: Path):
    from core.sinks import run_output_dir
    base = tmp_path / "outputs" / "runs"
    out = run_output_dir("abc123", base=str(base))
    assert os.path.isdir(out)
    assert out.endswith("run_id=abc123")


def test_export_run_events_to_jsonl(tmp_path: Path):
    from core.sinks import export_run_events_to_jsonl
    db = tmp_path / "exp.sqlite"
    summ = run_simulation(db_path=str(db), n_drones=2, n_trips=3, seed=42)
    out  = tmp_path / "out.jsonl"
    n, path = export_run_events_to_jsonl(
        str(db), summ["run_id"], out_path=str(out),
    )
    assert path == str(out)
    assert n   == summ["events_written"]
    assert os.path.getsize(out) > 0
    # The exported lines all belong to this run.
    import json
    with open(out, encoding="utf-8") as fh:
        for line in fh:
            obj = json.loads(line)
            assert obj["run_id"] == summ["run_id"]


@pytest.mark.slow
def test_run_comparison_chart_renders(tmp_path: Path):
    from core.visualizations import generate_charts
    db = tmp_path / "viz.sqlite"
    for scen in ("urban_dense", "rural_extended"):
        run_simulation(db_path=str(db), n_drones=3, n_trips=5, seed=42, scenario=scen)
    paths = generate_charts(db_path=str(db), out_dir=str(tmp_path / "charts"))
    p = Path(paths["run_comparison_profit"])
    assert p.exists() and p.stat().st_size > 0
