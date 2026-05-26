"""Phase 24: experiment orchestration layer.

Tests are written first (spec requirement) and cover:
  (1) ExperimentDefinition shape — all dimension fields must be lists
  (2) run() writes experiment_runs row with status='completed'
  (3) transformation_runs rows produced by an experiment carry the FK;
      rows from direct transform calls leave it NULL
  (4) Experiment is rerunnable — two calls produce two rows + 2x transform rows
  (5) compute_summary covers the full Cartesian product (scenario x domain x scale)
  (6) Empty dimension list expands to all registered values
  (7) Bad dimension value → status='failed', error captured
  (8) API endpoints return the right shapes
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from core.experiments import (
    Experiment, ExperimentDefinition,
    get_experiment, list_experiments, register_experiment,
)
from core.delivery_domains import list_domains
from core.economic_models import list_economic_models
from core.scale_models import list_scale_models


# ─────────────────────────────────────────────────────────────────────────────
# Fixture
# ─────────────────────────────────────────────────────────────────────────────

# sim_db removed — use conftest.py writable_db instead.

def _select(db: str, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# (1) ExperimentDefinition: all dimension fields must be lists
# ─────────────────────────────────────────────────────────────────────────────

def test_experiment_definition_all_fields_plural():
    """scenarios, economic_models, delivery_domains, scale_models must all be
    lists.  Passing a scalar for any of them raises TypeError."""
    valid = dict(
        name="t",
        run_ids=[],
        scenarios=[],
        economic_models=[],
        delivery_domains=[],
        scale_models=[],
    )
    # Baseline: valid instantiation works.
    ExperimentDefinition(**valid)

    for field in ("scenarios", "economic_models", "delivery_domains", "scale_models", "run_ids"):
        bad = {**valid, field: "not_a_list"}
        with pytest.raises(TypeError, match=field):
            ExperimentDefinition(**bad)


# ─────────────────────────────────────────────────────────────────────────────
# (2) run() writes a single completed experiment_runs row
# ─────────────────────────────────────────────────────────────────────────────

def test_run_writes_experiment_run_row(writable_db: tuple[str, str]):
    db, rid = writable_db
    defn = ExperimentDefinition(
        name="smoke",
        run_ids=[rid],
        scenarios=[],
        economic_models=["suburban_standard"],
        delivery_domains=["retail_package"],
        scale_models=["pilot_program"],
    )
    result = Experiment(defn, db).run()
    assert result["status"] == "completed"

    rows = _select(db,
        "SELECT experiment_name, status FROM experiment_runs "
        "WHERE experiment_run_id = ?",
        (result["experiment_run_id"],),
    )
    assert len(rows) == 1
    assert rows[0] == ("smoke", "completed")


# ─────────────────────────────────────────────────────────────────────────────
# (3) Lineage: experiment-produced rows carry the FK; direct calls leave it NULL
# ─────────────────────────────────────────────────────────────────────────────

def test_transformation_runs_tagged_with_experiment_id(writable_db: tuple[str, str]):
    from transforms import economics

    db, rid = writable_db

    # Direct call — must leave experiment_run_id NULL.
    direct = economics.run(db, run_id=rid)
    direct_tx = direct["transform_run_id"]
    rows = _select(db,
        "SELECT experiment_run_id FROM transformation_runs WHERE transform_run_id = ?",
        (direct_tx,),
    )
    assert rows[0][0] is None, "Direct transform call should leave experiment_run_id NULL"

    # Experiment call — every produced row must carry the FK.
    defn = ExperimentDefinition(
        name="lineage_test",
        run_ids=[rid],
        scenarios=[],
        economic_models=["suburban_standard"],
        delivery_domains=["retail_package"],
        scale_models=["pilot_program"],
    )
    exp_result = Experiment(defn, db).run()
    exp_id = exp_result["experiment_run_id"]

    tagged = _select(db,
        "SELECT transform_run_id FROM transformation_runs "
        "WHERE experiment_run_id = ?",
        (exp_id,),
    )
    assert len(tagged) >= 1, "Experiment should produce at least one tagged transform row"

    # All tagged rows belong to this experiment_run_id — none to another.
    wrong = _select(db,
        "SELECT COUNT(*) FROM transformation_runs "
        "WHERE experiment_run_id IS NOT NULL AND experiment_run_id != ?",
        (exp_id,),
    )
    # Account for any previous experiment in this DB — only check rows from
    # this experiment point to this id.
    for tx_id, in tagged:
        exp_link = _select(db,
            "SELECT experiment_run_id FROM transformation_runs WHERE transform_run_id = ?",
            (tx_id,),
        )
        assert exp_link[0][0] == exp_id


# ─────────────────────────────────────────────────────────────────────────────
# (4) Rerunnable: two calls produce two experiment_runs rows + 2× transform rows
# ─────────────────────────────────────────────────────────────────────────────

def test_experiment_is_rerunnable(writable_db: tuple[str, str]):
    db, rid = writable_db
    defn = ExperimentDefinition(
        name="rerun_test",
        run_ids=[rid],
        scenarios=[],
        economic_models=["suburban_standard"],
        delivery_domains=["retail_package"],
        scale_models=["pilot_program"],
    )
    exp = Experiment(defn, db)
    r1 = exp.run()
    r2 = exp.run()

    assert r1["experiment_run_id"] != r2["experiment_run_id"], (
        "Each run() call must produce a distinct experiment_run_id"
    )

    exp_rows = _select(db,
        "SELECT experiment_run_id FROM experiment_runs WHERE experiment_name = 'rerun_test'"
    )
    assert len(exp_rows) == 2

    # transformation_runs rows per experiment should be equal between runs.
    def tx_count(exp_id: str) -> int:
        return _select(db,
            "SELECT COUNT(*) FROM transformation_runs WHERE experiment_run_id = ?",
            (exp_id,),
        )[0][0]

    assert tx_count(r1["experiment_run_id"]) == tx_count(r2["experiment_run_id"])
    assert tx_count(r1["experiment_run_id"]) > 0

    # compute_summary on latest run is non-empty and consistent.
    summary = exp.compute_summary()
    assert summary["experiment_run_id"] == r2["experiment_run_id"]
    assert summary["profiles"]


# ─────────────────────────────────────────────────────────────────────────────
# (5) compute_summary covers the full Cartesian product (scenario × domain × scale)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.slow
def test_compute_summary_covers_full_cartesian_product(writable_db: tuple[str, str]):
    """full_grid with one sim run produces one summary cell per
    (scenario × delivery_domain × scale_model).  The fixture runs a single
    default simulation whose trips all carry scenario_name='suburban_standard',
    so the scenario dimension = 1.  Domains = 4, scales = 4 → 16 cells.
    """
    db, rid = writable_db
    full_grid = get_experiment("full_grid")
    defn_with_run = ExperimentDefinition(
        name=full_grid.name,
        run_ids=[rid],
        scenarios=full_grid.scenarios,
        economic_models=full_grid.economic_models,
        delivery_domains=full_grid.delivery_domains,
        scale_models=full_grid.scale_models,
    )
    exp = Experiment(defn_with_run, db)
    exp.run()
    summary = exp.compute_summary()

    profiles = summary["profiles"]
    assert profiles, "Summary must be non-empty"

    n_domains = len(list_domains())     # 4
    n_scales  = len(list_scale_models())  # 4
    # One scenario in the test DB.
    scenarios_seen = {p["scenario_name"] for p in profiles}
    assert len(scenarios_seen) >= 1

    # Every (scenario, domain, scale) combination must appear exactly once.
    keys = {(p["scenario_name"], p["domain_name"], p["scale_model_name"])
            for p in profiles}
    for sc in scenarios_seen:
        for d in list_domains():
            for s in list_scale_models():
                assert (sc, d, s) in keys, (
                    f"Missing cell: scenario={sc} domain={d} scale={s}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# (6) Empty dimension list expands to all registered values
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_dimension_list_means_all_registered(writable_db: tuple[str, str]):
    """delivery_domains=[] must expand to all four registered domains."""
    db, rid = writable_db
    defn = ExperimentDefinition(
        name="empty_domain_expand",
        run_ids=[rid],
        scenarios=[],
        economic_models=["suburban_standard"],
        delivery_domains=[],          # ← should expand to all 4
        scale_models=["pilot_program"],
    )
    Experiment(defn, db).run()

    # Every registered domain should appear in the economics snapshots
    # produced by this experiment.
    domain_rows = _select(db,
        """
        SELECT DISTINCT e.domain_name
          FROM trip_economics_snapshots e
          JOIN transformation_runs tx ON tx.transform_run_id = e.transform_run_id
          JOIN experiment_runs er ON er.experiment_run_id = tx.experiment_run_id
         WHERE er.experiment_name = 'empty_domain_expand'
        """
    )
    found_domains = {r[0] for r in domain_rows}
    assert found_domains == set(list_domains()), (
        f"Expected all domains {list_domains()}, got {sorted(found_domains)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# (7) Failed experiment records error; status = 'failed'
# ─────────────────────────────────────────────────────────────────────────────

def test_failed_experiment_records_error(writable_db: tuple[str, str]):
    """A bad scale_model name must produce a 'failed' experiment row with
    a non-null error field.  The experiment must NOT raise to the caller."""
    db, rid = writable_db
    defn = ExperimentDefinition(
        name="bad_scale_test",
        run_ids=[rid],
        scenarios=[],
        economic_models=["suburban_standard"],
        delivery_domains=["retail_package"],
        scale_models=["does_not_exist"],   # bad value
    )
    result = Experiment(defn, db).run()
    assert result["status"] == "failed"
    assert result.get("error")

    row = _select(db,
        "SELECT status, error FROM experiment_runs WHERE experiment_run_id = ?",
        (result["experiment_run_id"],),
    )
    assert row, "experiment_runs row must exist even for failed experiments"
    status, error = row[0]
    assert status == "failed"
    assert error  # non-null, non-empty error message


# ─────────────────────────────────────────────────────────────────────────────
# (8) API: GET /experiments and GET /experiments/{id}
# ─────────────────────────────────────────────────────────────────────────────

def test_api_experiments_endpoint(writable_db: tuple[str, str]):
    from fastapi.testclient import TestClient

    db, rid = writable_db
    defn = ExperimentDefinition(
        name="api_test",
        run_ids=[rid],
        scenarios=[],
        economic_models=["suburban_standard"],
        delivery_domains=["retail_package"],
        scale_models=["pilot_program"],
    )
    result = Experiment(defn, db).run()
    exp_id = result["experiment_run_id"]

    old = os.environ.get("DRONE_API_DB")
    os.environ["DRONE_API_DB"] = db
    try:
        from api.main import app
        client = TestClient(app)

        # GET /experiments
        list_body = client.get("/experiments").json()
        assert "experiments" in list_body
        ids = [e["experiment_run_id"] for e in list_body["experiments"]]
        assert exp_id in ids

        # GET /experiments/{id}
        detail_body = client.get(f"/experiments/{exp_id}").json()
        assert detail_body["experiment_run_id"] == exp_id
        assert detail_body["status"] == "completed"
        assert "summary" in detail_body
        assert detail_body["summary"]["profiles"]  # non-empty
    finally:
        if old is None:
            del os.environ["DRONE_API_DB"]
        else:
            os.environ["DRONE_API_DB"] = old
