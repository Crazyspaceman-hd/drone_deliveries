"""Synthetic economics: persistence, determinism, and comparative outputs."""

import sqlite3
from pathlib import Path

from core.simulator import run_simulation


ECON_COLUMNS = (
    "trip_distance_km",
    "estimated_energy_cost",
    "estimated_maintenance_cost",
    "estimated_operational_cost",
    "estimated_revenue",
    "estimated_profit",
    "emergency_return_penalty_applied",
)


def test_economics_columns_populated(seed42_db: Path):
    """Every trip has every economics column filled in after the run."""
    conn = sqlite3.connect(str(seed42_db))
    try:
        cols = ", ".join(ECON_COLUMNS)
        rows = conn.execute(f"SELECT trip_id, {cols} FROM trips").fetchall()
    finally:
        conn.close()

    assert rows, "expected at least one trip row"
    for trip_id, *vals in rows:
        for col, v in zip(ECON_COLUMNS, vals):
            assert v is not None, f"trip {trip_id} missing {col}"


def test_profit_calculations_deterministic(tmp_path: Path):
    """Same seed + scenario produces identical economics totals."""
    def _totals(db: Path) -> tuple[float, float, float]:
        run_simulation(db_path=str(db), n_drones=3, n_trips=10,
                       seed=42, scenario="suburban_standard")
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT ROUND(SUM(estimated_revenue),4), "
                "       ROUND(SUM(estimated_operational_cost),4), "
                "       ROUND(SUM(estimated_profit),4) "
                "  FROM trips"
            ).fetchone()
        finally:
            conn.close()
        return tuple(row)

    a = _totals(tmp_path / "a.sqlite")
    b = _totals(tmp_path / "b.sqlite")
    assert a == b


def test_aborted_trips_can_be_unprofitable(tmp_path: Path):
    """At least one aborted trip in rural_extended should run negative.

    rural_extended has a £60 emergency-return penalty and zero revenue on
    abort, so aborted trips must have estimated_profit < 0.
    """
    db = tmp_path / "rural.sqlite"
    # 100 trips × 10% emergency chance → expect roughly 10 aborts; plenty.
    run_simulation(db_path=str(db), n_drones=3, n_trips=100,
                   seed=42, scenario="rural_extended")
    conn = sqlite3.connect(str(db))
    try:
        aborted_profits = [r[0] for r in conn.execute(
            "SELECT estimated_profit FROM trips "
            "WHERE scenario_name='rural_extended' AND status='aborted'"
        ).fetchall()]
    finally:
        conn.close()
    assert aborted_profits, "expected at least one aborted trip"
    assert all(p < 0 for p in aborted_profits), (
        f"aborted trips were not all negative: {aborted_profits}"
    )


def test_scenarios_diverge_economically(tmp_path: Path):
    """Different scenarios must produce different total profits."""
    db = tmp_path / "multi.sqlite"
    for scen in ["urban_dense", "suburban_standard", "rural_extended"]:
        run_simulation(db_path=str(db), n_drones=3, n_trips=50,
                       seed=42, scenario=scen)
    conn = sqlite3.connect(str(db))
    try:
        profits = dict(conn.execute(
            "SELECT scenario_name, ROUND(SUM(estimated_profit), 2) "
            "  FROM trips WHERE scenario_name IS NOT NULL "
            " GROUP BY scenario_name"
        ).fetchall())
    finally:
        conn.close()
    assert len(profits) == 3
    # No two scenarios should land on the same total.
    assert len(set(profits.values())) == 3, f"profits collided: {profits}"


def test_scenario_economics_sql_runs(tmp_path: Path):
    """analytics/sql/scenario_economics.sql executes and returns per-scenario rows."""
    db = tmp_path / "econ.sqlite"
    for scen in ["urban_dense", "rural_extended"]:
        run_simulation(db_path=str(db), n_drones=3, n_trips=20,
                       seed=42, scenario=scen)

    sql = Path("analytics/sql/scenario_economics.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(sql).fetchall()
        headers = [d[0] for d in conn.execute(sql).description]
    finally:
        conn.close()

    seen = {r[0] for r in rows}
    assert "urban_dense"    in seen
    assert "rural_extended" in seen
    # Sanity: the column names we promised in the spec exist.
    for must_have in ("total_revenue", "total_operational_cost", "total_profit",
                      "avg_profit_per_trip", "emergency_return_count"):
        assert must_have in headers, f"missing column: {must_have}"


def test_profitability_chart_generated(seed42_db: Path, tmp_path: Path):
    """generate_charts produces scenario_profitability.png even with a single scenario."""
    from core.visualizations import generate_charts
    paths = generate_charts(db_path=str(seed42_db), out_dir=str(tmp_path / "charts"))
    p = Path(paths["scenario_profitability"])
    assert p.exists()
    assert p.suffix == ".png"
    assert p.stat().st_size > 0
