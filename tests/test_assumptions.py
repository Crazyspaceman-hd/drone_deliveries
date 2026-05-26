"""Assumption helpers, SQL, chart, and docs."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from core.assumptions import (
    FIELD_CATEGORIES, get_assumption_summary, get_bi_assumptions,
    get_scenario_assumptions,
)


def test_scenario_assumptions_non_empty():
    rows = get_scenario_assumptions()
    assert rows
    names = {r["name"] for r in rows}
    assert {"urban_dense", "suburban_standard", "rural_extended"} <= names


def test_every_field_has_a_category():
    """Every Scenario field appearing in the per-scenario row has a category."""
    for row in get_scenario_assumptions():
        for field in row:
            if field in ("name", "categories"):
                continue
            assert field in FIELD_CATEGORIES, f"uncategorised field: {field}"


def test_bi_assumptions_export_synthetic():
    bi = get_bi_assumptions()
    assert bi["category"] == "synthetic"
    assert bi["weights"]["W_COMPLETION"] > 0
    assert bi["thresholds"]["STRONG_SCORE_MIN"] > bi["thresholds"]["BORDERLINE_SCORE_MIN"]


def test_assumption_summary_bundles_everything():
    s = get_assumption_summary()
    for key in ("scenarios", "bi", "field_categories", "doc_path"):
        assert key in s
    assert s["doc_path"].endswith("assumptions.md")


def test_docs_assumptions_md_exists_and_substantial():
    """Narrative doc exists and is not a one-liner."""
    p = Path("docs/assumptions.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert len(text.splitlines()) > 40, "docs/assumptions.md looks too short"
    # Spot-check that both categories are explained in the narrative.
    lo = text.lower()
    assert "publicly_informed" in lo or "publicly informed" in lo
    assert "synthetic" in lo


def test_assumptions_cli_writes_markdown(tmp_path: Path):
    out = tmp_path / "rep.md"
    res = subprocess.run(
        [sys.executable, "run_assumptions_report.py", "--markdown", str(out)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert res.returncode == 0, res.stderr
    assert out.exists() and out.stat().st_size > 0
    md = out.read_text(encoding="utf-8")
    # Sanity: scenarios + BI sections rendered.
    assert "Scenario knobs" in md
    assert "Business-intelligence scoring" in md
    assert "urban_dense" in md
    assert "rural_extended" in md


def test_assumption_summary_sql_runs(seed42_db: Path):
    sql = Path("analytics/sql/assumption_summary.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(seed42_db))
    try:
        rows = conn.execute(sql).fetchall()
        headers = [d[0] for d in conn.execute(sql).description]
    finally:
        conn.close()
    assert rows
    for col in ("completion_rate_pct", "observed_avg_distance_km",
                "observed_emergency_rate", "observed_maintenance_rate"):
        assert col in headers, f"missing column: {col}"


@pytest.mark.slow
def test_operational_profile_chart_generated(seed42_db: Path, tmp_path: Path):
    from core.visualizations import generate_charts
    paths = generate_charts(db_path=str(seed42_db), out_dir=str(tmp_path / "charts"))
    p = Path(paths["scenario_operational_profile"])
    assert p.exists()
    assert p.suffix == ".png"
    assert p.stat().st_size > 0
