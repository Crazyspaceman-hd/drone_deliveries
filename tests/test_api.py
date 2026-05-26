"""Phase 18: FastAPI workbench backend.

Smoke + shape tests only.  We don't try to validate every field; the
underlying core modules already have dedicated tests.  Here we just
prove the routes are wired and return JSON of the right shape.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

fastapi      = pytest.importorskip("fastapi")
testclient   = pytest.importorskip("fastapi.testclient")

from core.simulator import run_simulation
from core.sinks import export_run_to_parquet  # noqa: F401 — ensures pyarrow present
from core.visualizations import generate_charts


# ─────────────────────────────────────────────────────────────────────────────
# Per-module workbench fixture: a tiny seeded DB + one rendered chart, with
# DRONE_API_DB / DRONE_API_CHARTS_DIR pointed at the temp paths via env vars.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def workbench(tmp_path_factory: pytest.TempPathFactory):
    workdir = tmp_path_factory.mktemp("api")
    db      = workdir / "delivery_system.sqlite"
    charts  = workdir / "charts"
    # Two scenarios so /runs returns >1.
    for scen in ("urban_dense", "rural_extended"):
        run_simulation(db_path=str(db), n_drones=2, n_trips=4,
                       seed=42, scenario=scen)
    generate_charts(db_path=str(db), out_dir=str(charts))

    old_db     = os.environ.get("DRONE_API_DB")
    old_charts = os.environ.get("DRONE_API_CHARTS_DIR")
    os.environ["DRONE_API_DB"]         = str(db)
    os.environ["DRONE_API_CHARTS_DIR"] = str(charts)
    try:
        # Late import so the env vars are picked up by the dependency helpers.
        from api.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        yield {
            "client":     client,
            "db":         str(db),
            "charts_dir": str(charts),
        }
    finally:
        if old_db     is None: del os.environ["DRONE_API_DB"]
        else:                  os.environ["DRONE_API_DB"]     = old_db
        if old_charts is None: del os.environ["DRONE_API_CHARTS_DIR"]
        else:                  os.environ["DRONE_API_CHARTS_DIR"] = old_charts


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_health(workbench):
    r = workbench["client"].get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_runs_list_returns_two_rows(workbench):
    r = workbench["client"].get("/runs")
    assert r.status_code == 200
    body = r.json()
    assert "runs" in body
    assert len(body["runs"]) == 2
    for run in body["runs"]:
        for key in ("run_id", "created_at", "seed", "scenario_names",
                    "simulator_version", "assumption_version"):
            assert key in run


def test_run_detail_404_for_unknown(workbench):
    r = workbench["client"].get("/runs/does-not-exist")
    assert r.status_code == 404


def test_run_detail_ok_for_real(workbench):
    list_resp = workbench["client"].get("/runs").json()
    rid = list_resp["runs"][0]["run_id"]
    r = workbench["client"].get(f"/runs/{rid}")
    assert r.status_code == 200
    assert r.json()["run_id"] == rid


def test_scenarios_summary_bundles_all_layers(workbench):
    r = workbench["client"].get("/scenarios/summary")
    assert r.status_code == 200
    body = r.json()
    for key in ("assumptions", "bi_rankings", "calibration"):
        assert key in body
    assert isinstance(body["bi_rankings"], list)


def test_validation_returns_structured_summary(workbench):
    r = workbench["client"].get("/validation")
    assert r.status_code == 200
    body = r.json()
    for key in ("results", "counts_by_severity", "failed_by_severity", "any_errors"):
        assert key in body
    assert all("rule_name" in row for row in body["results"])


def test_business_intelligence_top_level(workbench):
    r = workbench["client"].get("/business-intelligence")
    assert r.status_code == 200
    body = r.json()
    assert "rankings" in body
    assert "recommendations" in body


def test_delivery_displacement_returns_numeric_fields(workbench):
    r = workbench["client"].get("/analytics/delivery-displacement")
    assert r.status_code == 200
    body = r.json()
    assert "totals" in body
    for key in ("completed_drone_deliveries", "estimated_truck_delivery_cost",
                "estimated_drone_operational_cost", "estimated_cost_difference",
                "estimated_displacement_pct"):
        assert key in body["totals"]
        assert isinstance(body["totals"][key], (int, float))
    assert isinstance(body["by_scenario"], list) and body["by_scenario"]


def test_delivery_displacement_honors_truck_cost_query(workbench):
    r1 = workbench["client"].get(
        "/analytics/delivery-displacement?truck_cost_per_delivery=5"
    ).json()
    r2 = workbench["client"].get(
        "/analytics/delivery-displacement?truck_cost_per_delivery=20"
    ).json()
    # Higher cost per delivery → higher total truck baseline cost.
    assert r2["totals"]["estimated_truck_delivery_cost"] \
         > r1["totals"]["estimated_truck_delivery_cost"]


def test_charts_list_and_fetch(workbench):
    listing = workbench["client"].get("/charts").json()
    assert "charts" in listing
    assert listing["charts"]
    first = listing["charts"][0]
    r = workbench["client"].get(f"/charts/{first}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 0


def test_chart_path_traversal_rejected(workbench):
    r = workbench["client"].get("/charts/..%2Fdelivery_system.sqlite")
    # The route should refuse anything with slashes or .. — either 400 or 404
    # is acceptable depending on how the test client normalises.  We only
    # need to confirm we never serve the file.
    assert r.status_code in (400, 404)


# ── Phase 26: new UI-facing endpoints ───────────────────────────────────────

def test_runs_transforms_returns_flat_lineage(workbench):
    rid = workbench["client"].get("/runs").json()["runs"][0]["run_id"]
    r = workbench["client"].get(f"/runs/{rid}/transforms")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == rid
    assert isinstance(body["transforms"], list)
    assert body["transforms"], "default transform pipeline should populate this"
    for row in body["transforms"]:
        for k in ("transform_run_id", "transform_name", "transform_version",
                  "created_at", "parameters_json"):
            assert k in row


def test_runs_transforms_404_for_unknown_run(workbench):
    r = workbench["client"].get("/runs/does-not-exist/transforms")
    assert r.status_code == 404


def test_domain_scale_matrix_shape(workbench):
    # The workbench fixture auto-ran economics+scale with retail_package +
    # default scale model.  That alone is enough to populate ≥1 cell.
    r = workbench["client"].get("/analytics/domain-scale-matrix")
    assert r.status_code == 200
    body = r.json()
    for k in ("domains", "scale_models", "cells", "best_cell", "worst_cell"):
        assert k in body
    assert isinstance(body["domains"], list)
    assert isinstance(body["scale_models"], list)
    assert isinstance(body["cells"], list)
    if body["cells"]:
        cell = body["cells"][0]
        for k in ("scenario_name", "domain_name", "scale_model_name",
                  "avg_revenue", "avg_operational_cost", "avg_overhead",
                  "avg_effective_profit", "break_even_rate", "trip_count"):
            assert k in cell


def test_missing_db_returns_404(tmp_path: Path):
    """Wipe DRONE_API_DB to a non-existent path and confirm 404."""
    old = os.environ.get("DRONE_API_DB")
    os.environ["DRONE_API_DB"] = str(tmp_path / "absent.sqlite")
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        r = client.get("/runs")
        assert r.status_code == 404
    finally:
        if old is None: del os.environ["DRONE_API_DB"]
        else:           os.environ["DRONE_API_DB"] = old
