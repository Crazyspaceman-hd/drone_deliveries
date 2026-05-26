"""BI: scoring, ranking, recommendations, SQL, chart."""

import sqlite3
from pathlib import Path

import pytest

from core.business_intelligence import (
    BORDERLINE_SCORE_MIN, STRONG_SCORE_MIN,
    compute_scenario_metrics, feasibility_label, feasibility_score,
    generate_feasibility_report, generate_recommendations,
    generate_scenario_rankings,
)

# multi_scenario_db fixture is provided by conftest.py (session-scoped).
# All tests that depend on it are marked @pytest.mark.slow.


@pytest.mark.slow
def test_metrics_contain_three_scenarios(multi_scenario_db: Path):
    rows = compute_scenario_metrics(str(multi_scenario_db))
    seen = {r["scenario_name"] for r in rows}
    assert seen == {"urban_dense", "suburban_standard", "rural_extended"}


def test_feasibility_label_thresholds():
    assert feasibility_label(STRONG_SCORE_MIN)         == "strong_candidate"
    assert feasibility_label(BORDERLINE_SCORE_MIN)     == "borderline"
    assert feasibility_label(BORDERLINE_SCORE_MIN - 1) == "poor_candidate"


@pytest.mark.slow
def test_rankings_deterministic(multi_scenario_db: Path):
    a = generate_scenario_rankings(str(multi_scenario_db))
    b = generate_scenario_rankings(str(multi_scenario_db))
    assert [r["scenario_name"]     for r in a] == [r["scenario_name"]     for r in b]
    assert [r["feasibility_score"] for r in a] == [r["feasibility_score"] for r in b]


@pytest.mark.slow
def test_scores_differ_between_scenarios(multi_scenario_db: Path):
    rows = generate_scenario_rankings(str(multi_scenario_db))
    scores = [r["feasibility_score"] for r in rows]
    assert len(set(scores)) == 3, f"feasibility scores collided: {scores}"


@pytest.mark.slow
def test_rural_ranks_worse_than_urban(multi_scenario_db: Path):
    """Under the current built-in cost model, rural must score below urban."""
    rows = {r["scenario_name"]: r for r in generate_scenario_rankings(str(multi_scenario_db))}
    assert rows["rural_extended"]["feasibility_score"] < rows["urban_dense"]["feasibility_score"]


@pytest.mark.slow
def test_recommendations_non_empty(multi_scenario_db: Path):
    recs = generate_recommendations(str(multi_scenario_db))
    assert recs
    assert all(isinstance(r, str) and r.strip() for r in recs)
    # The best/worst-line rule should always fire when >= 2 scenarios exist.
    joined = " | ".join(recs).lower()
    assert "strongest feasibility profile" in joined
    assert "weakest feasibility profile"   in joined


@pytest.mark.slow
def test_feasibility_summary_sql_runs(multi_scenario_db: Path):
    sql = Path("analytics/sql/feasibility_summary.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(multi_scenario_db))
    try:
        rows    = conn.execute(sql).fetchall()
        headers = [d[0] for d in conn.execute(sql).description]
    finally:
        conn.close()
    seen = {r[0] for r in rows}
    assert seen == {"urban_dense", "suburban_standard", "rural_extended"}
    for col in ("completion_rate_pct", "avg_profit_per_trip", "emergency_return_rate",
                "maintenance_events_per_trip", "profit_margin_pct"):
        assert col in headers, f"missing column: {col}"


@pytest.mark.slow
def test_feasibility_chart_generated(multi_scenario_db: Path, tmp_path: Path):
    from core.visualizations import generate_charts
    paths = generate_charts(db_path=str(multi_scenario_db), out_dir=str(tmp_path / "charts"))
    p = Path(paths["scenario_feasibility"])
    assert p.exists()
    assert p.suffix == ".png"
    assert p.stat().st_size > 0


@pytest.mark.slow
def test_report_bundles_everything(multi_scenario_db: Path):
    report = generate_feasibility_report(str(multi_scenario_db))
    assert "rankings"        in report
    assert "recommendations" in report
    assert "scoring_weights" in report
    assert report["scoring_weights"]["STRONG_SCORE_MIN"] == STRONG_SCORE_MIN
