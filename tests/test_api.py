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
    # is acceptable depending on how the test client normalizes.  We only
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


def test_volume_sensitivity_endpoint_shape(workbench):
    r = workbench["client"].get("/analytics/volume-sensitivity")
    assert r.status_code == 200
    body = r.json()
    for k in ("rows", "capacity_model", "capacity_assumptions",
              "sweep_points", "registry_version", "domains",
              "best_row", "worst_row"):
        assert k in body, f"missing key: {k}"
    assert body["capacity_model"] == "pilot_capacity"   # Phase 28 default
    assert len(body["sweep_points"]) >= 10
    if body["rows"]:
        # Row carries Phase 28 capacity-coupled fields + Phase 29 response fields.
        for k in ("delivery_domain", "capacity_model", "deliveries_per_day",
                  # Phase 28 capacity
                  "required_drones", "required_operators",
                  "required_chargers", "daily_capacity_overhead",
                  "capacity_overhead_per_delivery",
                  # Source economics
                  "avg_operational_cost", "avg_revenue", "avg_source_profit",
                  # Phase 29 response
                  "saturation_volume_per_day",
                  "domain_efficiency_credit", "domain_value_decay",
                  "net_domain_response",
                  "adjusted_avg_operational_cost", "adjusted_avg_revenue",
                  # Composite
                  "avg_effective_profit", "break_even_rate", "trip_count"):
            assert k in body["rows"][0], f"missing row key: {k}"


def test_volume_sensitivity_endpoint_honors_capacity_model_param(workbench):
    pilot = workbench["client"].get(
        "/analytics/volume-sensitivity?capacity_model=pilot_capacity"
    ).json()
    urban = workbench["client"].get(
        "/analytics/volume-sensitivity?capacity_model=dense_urban_capacity"
    ).json()
    assert pilot["capacity_model"] == "pilot_capacity"
    assert urban["capacity_model"] == "dense_urban_capacity"
    # Required drones at d=1000 must differ — productivity rates do.
    if pilot["rows"] and urban["rows"]:
        p1k = next(r for r in pilot["rows"] if r["deliveries_per_day"] == 1000)
        u1k = next(r for r in urban["rows"] if r["deliveries_per_day"] == 1000)
        assert p1k["required_drones"] > u1k["required_drones"]


def test_viability_summary_endpoint_shape(workbench):
    r = workbench["client"].get("/analytics/viability-summary")
    assert r.status_code == 200
    body = r.json()
    for k in ("cells", "capacity_models", "delivery_domains",
              "pain_points", "viability_margin_max_abs"):
        assert k in body
    assert body["capacity_models"], "capacity_models list is empty"
    if body["cells"]:
        cell = body["cells"][0]
        for k in ("capacity_model", "delivery_domain", "addressable_ceiling",
                  "breakeven_deliveries_per_day",
                  "viable_within_addressable_demand", "state",
                  "viability_margin"):
            assert k in cell, f"missing cell key: {k}"
        assert cell["state"] in ("viable", "beyond", "never")
    # Pain-points block shape
    pp = body["pain_points"]
    for k in ("diagnostics", "constraint_counts", "observations",
              "dominant_cost_counts"):
        assert k in pp
    if pp["diagnostics"]:
        d = pp["diagnostics"][0]
        for k in ("capacity_model", "delivery_domain", "state",
                  "dominant_constraint", "anchor_overhead_per_delivery",
                  "anchor_profit_before_overhead", "gap_at_anchor",
                  "cost_breakdown_at_anchor", "dominant_cost_component",
                  "dominant_cost_share"):
            assert k in d


def test_whatif_endpoint_capacity(workbench):
    """POST /experiments/what-if with a capacity sweep returns the
    synthetic names and records an experiment."""
    r = workbench["client"].post("/experiments/what-if", json={
        "dimension": "capacity_model",
        "base":      "pilot_capacity",
        "parameter": "operator_to_drone_ratio",
        "values":    [0.45, 0.30],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dimension"] == "capacity_model"
    assert "pilot_capacity@operator_to_drone_ratio=0.45" in body["synthetic_names"]
    assert body["experiment_name"].startswith("_whatif_")
    assert "next_step" in body


def test_whatif_endpoint_validates_payload(workbench):
    r = workbench["client"].post("/experiments/what-if", json={
        "dimension": "capacity_model", "base": "pilot_capacity",
        # missing parameter + values
    })
    assert r.status_code == 422


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
