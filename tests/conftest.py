"""
Shared fixtures.

Session-scoped DB fixtures are built once for the entire test run;
per-test writable copies are obtained by calling ``shutil.copy`` rather
than re-running the simulator.  This is the main lever for keeping the
test suite fast.

Fixture taxonomy
─────────────────
  seed42_db          (session) — full pipeline run (transforms applied)
  raw_sim_db         (session) — sim only, transforms NOT run (derived
                                 columns are NULL)
  emergency_db       (session) — seed=1, contains at least one emergency_return
  multi_scenario_db  (session) — 3 scenarios × 100 trips; used by calibration
                                 and BI tests.  @pytest.mark.slow guards every
                                 test that depends on it so the fixture is
                                 never built on the fast path.
  telemetry_db       (session) — 2 scenarios × 20 trips; telemetry/transform tests
  hybrid_db          (session) — 2 scenarios × 40 trips; hybrid-logistics tests
  empty_db           (function) — schema only, no simulation data

  writable_db        (function) — per-test writable copy of seed42_db
  writable_raw_db    (function) — per-test writable copy of raw_sim_db
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from core.setup_db import create_db
from core.simulator import run_simulation

# Sibling import — tests/ isn't a package, so add its own dir to sys.path
# before importing.  Pytest already does this implicitly during collection
# but we run conftest before collection completes.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
from baselines import expected_events


# Phase 20: pull the expected event count from the versioned baseline
# registry instead of hard-coding it.  See ``tests/baselines.py`` for
# the version history (counts shifted at Phase 6/7/8/14; Phase 20 is
# unchanged from Phase 14 because no event emission changed).
SEED42_EVENTS_WRITTEN  = expected_events(seed=42)
SEED42_TRIPS_REQUESTED = 10
SEED42_TRIPS_COMPLETED = 10


def _first_run_id(db_path: Path) -> str:
    """Return the earliest simulation_runs.run_id in *db_path*."""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT run_id FROM simulation_runs ORDER BY created_at ASC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()


# ── Session-scoped source DBs (built once per test run) ──────────────────────

@pytest.fixture(scope="session")
def seed42_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A SQLite DB pre-populated with the seed=42 simulation (transforms applied)."""
    db_dir  = tmp_path_factory.mktemp("seed42")
    db_path = db_dir / "delivery_system.sqlite"
    run_simulation(db_path=str(db_path), n_drones=3, n_trips=10, seed=42)
    return db_path


@pytest.fixture(scope="session")
def raw_sim_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Seed=42 simulation with transforms NOT auto-run.

    Derived columns (fulfillment_mode, estimated_profit, …) are NULL
    until a transform explicitly runs against this DB.  Source for the
    ``writable_raw_db`` per-test copies used by ``test_transforms.py``.
    """
    db_dir  = tmp_path_factory.mktemp("raw_sim")
    db_path = db_dir / "delivery_system_raw.sqlite"
    run_simulation(
        db_path=str(db_path), n_drones=3, n_trips=10, seed=42,
        run_transforms=False,
    )
    return db_path


# ── Per-test writable copies (fast: file copy, not re-simulation) ─────────────

@pytest.fixture
def writable_db(seed42_db: Path, tmp_path: Path) -> tuple[str, str]:
    """A writable per-test copy of the session seed=42 DB.

    Use this in place of a local ``raw_db`` fixture that calls
    ``run_simulation``.  ``shutil.copy`` is ~1 ms; re-running the
    simulator is ~300 ms.  Returns ``(db_path_str, run_id)``.
    """
    db = tmp_path / "test.sqlite"
    shutil.copy(seed42_db, db)
    return str(db), _first_run_id(db)


@pytest.fixture
def writable_raw_db(raw_sim_db: Path, tmp_path: Path) -> tuple[str, str]:
    """A writable per-test copy of the raw (transforms-not-run) session DB.

    Derived columns are NULL until the test explicitly runs a transform.
    Returns ``(db_path_str, run_id)``.
    """
    db = tmp_path / "test_raw.sqlite"
    shutil.copy(raw_sim_db, db)
    return str(db), _first_run_id(db)


# ── Other session fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def seed42_summary(seed42_db: Path) -> dict:
    """Re-derive the summary dict for the seed=42 DB without re-running."""
    conn = sqlite3.connect(str(seed42_db))
    try:
        events_written = conn.execute(
            "SELECT COUNT(*) FROM delivery_events"
        ).fetchone()[0]
        trips_completed = conn.execute(
            "SELECT COUNT(*) FROM trips WHERE status = 'completed'"
        ).fetchone()[0]
        event_counts_by_type = dict(conn.execute(
            "SELECT event_type, COUNT(*) FROM delivery_events GROUP BY event_type"
        ).fetchall())
    finally:
        conn.close()
    return {
        "events_written":       events_written,
        "trips_requested":      SEED42_TRIPS_REQUESTED,
        "trips_completed":      trips_completed,
        "event_counts_by_type": event_counts_by_type,
    }


@pytest.fixture(scope="session")
def emergency_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A DB whose seeded run is known to contain at least one emergency_return.

    Used by the emergency_return projection test now that seed=42's only
    emergency event was knocked out by the Phase 8 return-leg RNG draws.
    """
    db_dir  = tmp_path_factory.mktemp("emergency")
    db_path = db_dir / "delivery_system.sqlite"
    run_simulation(db_path=str(db_path), n_drones=3, n_trips=10, seed=1)
    return db_path


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """A freshly-initialised DB with schema only."""
    db_path = tmp_path / "empty.sqlite"
    create_db(str(db_path))
    return db_path


# ── Heavy multi-scenario session fixtures ────────────────────────────────────
# These are expensive to build (100–300 trips across multiple scenarios).
# Every test that requests one of these fixtures must be decorated with
# ``@pytest.mark.slow`` so that ``pytest -m "not slow"`` skips both the test
# and the fixture build.

@pytest.fixture(scope="session")
def multi_scenario_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One DB with all three built-in scenarios populated (100 trips each).

    Shared by ``test_calibration.py`` and ``test_business_intelligence.py``
    to avoid building 300 trips twice (once per module).
    All consumer tests must be marked ``@pytest.mark.slow``.
    """
    db = tmp_path_factory.mktemp("multi_scen") / "multi.sqlite"
    for scen in ["urban_dense", "suburban_standard", "rural_extended"]:
        run_simulation(db_path=str(db), n_drones=3, n_trips=100,
                       seed=42, scenario=scen)
    return db


@pytest.fixture(scope="session")
def telemetry_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Multi-scenario DB so telemetry transform has scenarios to group on."""
    db = tmp_path_factory.mktemp("telemetry") / "x.sqlite"
    for scen in ("urban_dense", "rural_extended"):
        run_simulation(db_path=str(db), n_drones=3, n_trips=20,
                       seed=42, scenario=scen)
    return db


@pytest.fixture(scope="session")
def hybrid_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two-scenario DB for hybrid-logistics tests."""
    db = tmp_path_factory.mktemp("hybrid") / "x.sqlite"
    for scen in ("urban_dense", "rural_extended"):
        run_simulation(db_path=str(db), n_drones=3, n_trips=40,
                       seed=42, scenario=scen)
    return db
