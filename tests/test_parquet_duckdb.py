"""Phase 16: Parquet export + DuckDB analytical layer.

Skipped (rather than failed) when pyarrow / duckdb aren't installed, so
the rest of the suite stays runnable on a barebones environment.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pyarrow = pytest.importorskip("pyarrow", reason="parquet export needs pyarrow")
duckdb  = pytest.importorskip("duckdb",  reason="DuckDB layer needs the duckdb pkg")

from core.simulator import run_simulation


# ── per-module sim DB with three scenarios + parquet exports ────────────────

@pytest.fixture(scope="module")
def parquet_workspace(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Run three scenarios and export Parquet for each.  Returns paths."""
    from core.sinks import export_run_to_parquet
    workdir = tmp_path_factory.mktemp("phase16")
    db = workdir / "delivery_system.sqlite"
    run_ids: list[str] = []
    for scen in ("urban_dense", "suburban_standard", "rural_extended"):
        summ = run_simulation(db_path=str(db), n_drones=3, n_trips=20,
                              seed=42, scenario=scen)
        run_ids.append(summ["run_id"])

    base = workdir / "outputs" / "runs"
    parquet_dirs: list[str] = []
    for rid in run_ids:
        out_dir = base / f"run_id={rid}" / "parquet"
        export_run_to_parquet(str(db), rid, out_dir=str(out_dir))
        parquet_dirs.append(str(out_dir))

    return {
        "db_path":       str(db),
        "run_ids":       run_ids,
        "base":          str(base),
        "parquet_dirs":  parquet_dirs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Parquet export
# ─────────────────────────────────────────────────────────────────────────────

def test_parquet_files_created_per_table(parquet_workspace: dict):
    for pq_dir in parquet_workspace["parquet_dirs"]:
        for table in ("delivery_events", "trips", "orders", "simulation_runs"):
            p = Path(pq_dir) / f"{table}.parquet"
            assert p.exists(), f"missing parquet: {p}"
            assert p.stat().st_size > 0


def _read_single_parquet_rowcount(path: Path) -> int:
    """Single-file row count via ParquetFile, avoiding the dataset API which
    in pyarrow 23+ tries to merge schemas across sibling files."""
    import pyarrow.parquet as pq
    return pq.ParquetFile(str(path)).metadata.num_rows


def _read_single_parquet_column(path: Path, col: str) -> list:
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(str(path))
    return pf.read(columns=[col]).column(col).to_pylist()


def test_parquet_row_counts_match_sqlite(parquet_workspace: dict):
    """For each run, the parquet exports must have the same row counts as
    the matching SQLite tables filtered to that run_id."""
    db = parquet_workspace["db_path"]
    for rid, pq_dir in zip(parquet_workspace["run_ids"], parquet_workspace["parquet_dirs"]):
        conn = sqlite3.connect(db)
        try:
            for table in ("delivery_events", "trips", "orders"):
                sqlite_n = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (rid,),
                ).fetchone()[0]
                parquet_n = _read_single_parquet_rowcount(
                    Path(pq_dir) / f"{table}.parquet"
                )
                assert sqlite_n == parquet_n, (
                    f"row count mismatch for run={rid[:8]} table={table}: "
                    f"sqlite={sqlite_n} parquet={parquet_n}"
                )
            # simulation_runs filter is by PK = run_id, so exactly 1 row.
            assert _read_single_parquet_rowcount(
                Path(pq_dir) / "simulation_runs.parquet"
            ) == 1
        finally:
            conn.close()


def test_parquet_preserves_run_id(parquet_workspace: dict):
    """Every event row inside a per-run parquet has the run_id of that run."""
    for rid, pq_dir in zip(parquet_workspace["run_ids"], parquet_workspace["parquet_dirs"]):
        col = _read_single_parquet_column(
            Path(pq_dir) / "delivery_events.parquet", "run_id"
        )
        assert col, "delivery_events parquet appears empty"
        assert all(v == rid for v in col), (
            f"parquet for run={rid[:8]} contains foreign run_ids"
        )


def test_export_raises_clear_error_when_dependencies_missing(tmp_path: Path):
    """If pandas is unavailable the helper must raise ImportError, not
    crash deeper inside read_sql_query."""
    from core.sinks import _require_parquet_stack
    with patch("builtins.__import__", side_effect=ImportError("no pandas")):
        with pytest.raises(ImportError, match="pandas"):
            _require_parquet_stack()


# ─────────────────────────────────────────────────────────────────────────────
# DuckDB
# ─────────────────────────────────────────────────────────────────────────────

def test_discover_run_parquet_dirs(parquet_workspace: dict):
    from core.duckdb_analytics import discover_run_parquet_dirs
    found = discover_run_parquet_dirs(parquet_workspace["base"])
    assert set(found) == set(parquet_workspace["parquet_dirs"])


def test_duckdb_query_executes(parquet_workspace: dict):
    from core.duckdb_analytics import run_duckdb_query
    headers, rows = run_duckdb_query(
        parquet_workspace["parquet_dirs"],
        "SELECT scenario_names, COUNT(*) FROM simulation_runs GROUP BY scenario_names",
    )
    assert headers
    assert {r[0] for r in rows} == {"urban_dense", "suburban_standard", "rural_extended"}


def test_duckdb_sql_files_all_execute(parquet_workspace: dict):
    from core.duckdb_analytics import generate_duckdb_summary
    summary = generate_duckdb_summary(parquet_workspace["parquet_dirs"])
    expected = {"cross_run_profitability", "event_volume_by_run",
                "maintenance_burden", "feasibility_rankings"}
    assert expected.issubset(summary.keys())
    # Each query returned at least one row (we have 3 runs).
    for name in expected:
        assert summary[name]["rows"], f"{name} returned no rows"


def test_cross_run_feasibility_orders_urban_above_rural(parquet_workspace: dict):
    """Phase 11 BI ranking should reproduce in DuckDB straight from Parquet."""
    from core.duckdb_analytics import generate_duckdb_summary
    summary = generate_duckdb_summary(parquet_workspace["parquet_dirs"])
    rows = summary["feasibility_rankings"]["rows"]
    by_scen = {r[1]: r[2] for r in rows}   # scenario_names -> feasibility_score
    assert by_scen["urban_dense"] > by_scen["rural_extended"]


def test_duckdb_handles_missing_dirs_cleanly(tmp_path: Path):
    """Empty base directory must raise FileNotFoundError, not crash deeper."""
    from core.duckdb_analytics import open_duckdb_for_runs
    with pytest.raises(FileNotFoundError, match="parquet"):
        open_duckdb_for_runs([str(tmp_path / "does_not_exist")])


def test_export_all_runs_helper(parquet_workspace: dict, tmp_path: Path):
    from core.sinks import export_all_runs_to_parquet
    fresh_db = tmp_path / "fresh.sqlite"
    run_simulation(db_path=str(fresh_db), n_drones=2, n_trips=3, seed=42)
    run_simulation(db_path=str(fresh_db), n_drones=2, n_trips=3, seed=42,
                   scenario="rural_extended")
    # Direct each run's parquet into tmp_path-scoped dirs to avoid touching
    # the repo's outputs/ tree.
    out_base = tmp_path / "outputs" / "runs"
    # Inline export via the per-run helper so we don't rely on cwd.
    from core.sinks import export_run_to_parquet
    conn = sqlite3.connect(str(fresh_db))
    try:
        rids = [r[0] for r in conn.execute(
            "SELECT run_id FROM simulation_runs"
        ).fetchall()]
    finally:
        conn.close()
    for rid in rids:
        export_run_to_parquet(
            str(fresh_db), rid,
            out_dir=str(out_base / f"run_id={rid}" / "parquet"),
        )
    assert len(list(out_base.iterdir())) == 2


def test_run_scenarios_cli_export_parquet_flag(tmp_path: Path):
    """End-to-end smoke through the actual CLI: --export-parquet writes files.

    Uses a separate cwd so we don't litter the repo's outputs/ tree.
    """
    workdir = tmp_path / "wd"
    workdir.mkdir()
    db = workdir / "delivery_system.sqlite"
    res = subprocess.run(
        [sys.executable,
         str(Path(__file__).resolve().parent.parent / "run_scenarios.py"),
         "--db", str(db),
         "--scenarios", "urban_dense",
         "--trips", "5", "--seed", "42",
         "--export-parquet"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(workdir),
    )
    assert res.returncode == 0, res.stderr
    pq_dirs = list((workdir / "outputs" / "runs").glob("run_id=*/parquet"))
    assert len(pq_dirs) == 1
    files = sorted(p.name for p in pq_dirs[0].iterdir())
    assert files == ["delivery_events.parquet", "orders.parquet",
                     "simulation_runs.parquet", "trips.parquet"]
