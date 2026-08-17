"""Scenario loading, determinism, and comparative behavior."""

import sqlite3
from pathlib import Path

import pytest

from core.scenarios import (
    DEFAULT_SCENARIO_NAME, Scenario, get_scenario, list_scenarios,
)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))   # so 'baselines' is importable
from baselines import expected_events            # noqa: E402

from core.simulator import run_simulation


def test_list_scenarios_contains_builtins():
    names = list_scenarios()
    assert "urban_dense"       in names
    assert "suburban_standard" in names
    assert "rural_extended"    in names


def test_get_scenario_by_name_and_default():
    sc = get_scenario("urban_dense")
    assert isinstance(sc, Scenario)
    assert sc.name == "urban_dense"
    assert get_scenario(None).name == DEFAULT_SCENARIO_NAME
    assert get_scenario(sc) is sc


def test_get_scenario_unknown_raises():
    with pytest.raises(KeyError):
        get_scenario("does_not_exist")


def _run(tmp: Path, scenario: str, seed: int = 42) -> dict:
    db = tmp / f"{scenario}_{seed}.sqlite"
    return run_simulation(db_path=str(db), n_drones=3, n_trips=10,
                          seed=seed, scenario=scenario)


def test_same_seed_same_scenario_is_deterministic(tmp_path: Path):
    a = _run(tmp_path / "a", "urban_dense")
    b = _run(tmp_path / "b", "urban_dense")
    assert a["events_written"]       == b["events_written"]
    assert a["event_counts_by_type"] == b["event_counts_by_type"]


def test_default_scenario_is_suburban_standard(tmp_path: Path):
    """Calling run_simulation without scenario keeps the historical baseline."""
    db = tmp_path / "default.sqlite"
    summ = run_simulation(db_path=str(db), n_drones=3, n_trips=10, seed=42)
    assert summ["scenario"]       == "suburban_standard"
    # Pinned to the current simulator version via tests/baselines.py.
    # Bump SIMULATOR_VERSION in core/runs.py + add an entry there when the
    # operational event stream legitimately changes.
    assert summ["events_written"] == expected_events(seed=42)


def test_scenarios_produce_different_outputs(tmp_path: Path):
    urban = _run(tmp_path / "u", "urban_dense")
    rural = _run(tmp_path / "r", "rural_extended")
    # Same seed + same trip count, but the knobs are different — total event
    # counts must visibly diverge.
    assert urban["events_written"] != rural["events_written"], (
        f"scenarios produced identical event totals: {urban['events_written']}"
    )


def test_events_and_trips_carry_scenario_name(tmp_path: Path):
    db = tmp_path / "tag.sqlite"
    run_simulation(db_path=str(db), n_drones=3, n_trips=5,
                   seed=42, scenario="urban_dense")
    conn = sqlite3.connect(str(db))
    try:
        ev_scenarios = {r[0] for r in conn.execute(
            "SELECT DISTINCT scenario_name FROM delivery_events "
            "WHERE scenario_name IS NOT NULL"
        ).fetchall()}
        trip_scenarios = {r[0] for r in conn.execute(
            "SELECT DISTINCT scenario_name FROM trips "
            "WHERE scenario_name IS NOT NULL"
        ).fetchall()}
    finally:
        conn.close()
    assert ev_scenarios   == {"urban_dense"}
    assert trip_scenarios == {"urban_dense"}


def test_scenario_summary_sql_runs(tmp_path: Path):
    """The scenario_summary.sql analytics query executes and groups by scenario."""
    db = tmp_path / "multi.sqlite"
    for scen in ["urban_dense", "rural_extended"]:
        run_simulation(db_path=str(db), n_drones=3, n_trips=10,
                       seed=42, scenario=scen)

    sql = Path("analytics/sql/scenario_summary.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    seen = {r[0] for r in rows}
    assert "urban_dense"    in seen
    assert "rural_extended" in seen
