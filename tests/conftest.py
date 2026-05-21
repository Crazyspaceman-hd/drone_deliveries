"""
Shared fixtures.

The seed=42 simulation is the workhorse scenario for several tests, so
it is built once per session into a temp directory and reused.  Tests
that need an empty DB use their own fixture.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.setup_db import create_db
from core.simulator import run_simulation


# Expected outcomes for run_simulation(n_drones=3, n_trips=10, seed=42).
# Confirmed during Phase 2/3; the simulator is deterministic.
SEED42_EVENTS_WRITTEN  = 172
SEED42_TRIPS_REQUESTED = 10
SEED42_TRIPS_COMPLETED = 9


@pytest.fixture(scope="session")
def seed42_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A SQLite DB pre-populated with the seed=42 simulation."""
    db_dir = tmp_path_factory.mktemp("seed42")
    db_path = db_dir / "delivery_system.sqlite"
    run_simulation(db_path=str(db_path), n_drones=3, n_trips=10, seed=42)
    return db_path


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


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """A freshly-initialised DB with schema only."""
    db_path = tmp_path / "empty.sqlite"
    create_db(str(db_path))
    return db_path
