"""Phase 23: scale-model overlays + trip_scale_snapshots.

Most tests are *separation invariants* — the scale transform must
amortize fleet-wide overhead without touching any source-side table
(events, telemetry, trips, economics snapshots).
"""

from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # baselines.py

from core.scale_models import (
    DEFAULT_SCALE_MODEL_NAME, SCALE_MODEL_REGISTRY_VERSION, ScaleModel,
    get_scale_model, list_scale_models,
)
from transforms import economics, scale


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures + helpers
# ─────────────────────────────────────────────────────────────────────────────

# writable_db removed — use conftest.py writable_db instead.

def _select(db: str, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Registry smoke
# ─────────────────────────────────────────────────────────────────────────────

def test_registry_contains_four_builtins():
    assert set(list_scale_models()) == {
        "pilot_program", "regional_network",
        "urban_dense_fleet", "national_scale",
    }


def test_default_is_pilot_program():
    assert DEFAULT_SCALE_MODEL_NAME == "pilot_program"
    assert get_scale_model(None).name == "pilot_program"


def test_unknown_scale_raises():
    with pytest.raises(KeyError):
        get_scale_model("does_not_exist")


def test_default_pipeline_writes_one_scale_row_per_trip(writable_db):
    """Smoke (j): auto-run produces a scale snapshot per trip with
    pilot_program tag."""
    db, _rid = writable_db
    rows = _select(
        db, "SELECT trip_id, scale_model_name FROM trip_scale_snapshots"
    )
    n_trips = _select(db, "SELECT COUNT(*) FROM trips")[0][0]
    assert len(rows) == n_trips
    assert {r[1] for r in rows} == {"pilot_program"}


# ─────────────────────────────────────────────────────────────────────────────
# Lineage
# ─────────────────────────────────────────────────────────────────────────────

def test_parameters_json_captures_scale_model_and_registry(writable_db):
    """Invariant (g): each scale recompute records scale_model +
    source_snapshot_run_id + registry version in parameters_json."""
    db, _rid = writable_db
    scale.run(db, scale_model="urban_dense_fleet")
    rows = _select(
        db,
        "SELECT parameters_json FROM transformation_runs "
        "WHERE transform_name = 'scale' ORDER BY created_at DESC LIMIT 1"
    )
    assert rows, "no scale row in transformation_runs"
    import json
    body = json.loads(rows[0][0])
    assert body["scale_model"]                   == "urban_dense_fleet"
    assert body["registry_versions"]["scale_model"] == SCALE_MODEL_REGISTRY_VERSION
    assert "source_snapshot_run_id" in body


def test_every_scale_snapshot_resolves_to_an_economics_snapshot(writable_db):
    """Invariant (h): no orphan source_snapshot_run_id values."""
    db, _rid = writable_db
    scale.run(db, scale_model="regional_network")
    orphan_count = _select(
        db,
        """
        SELECT COUNT(*) FROM trip_scale_snapshots s
         WHERE s.source_snapshot_run_id NOT IN
               (SELECT transform_run_id FROM trip_economics_snapshots)
        """,
    )[0][0]
    assert orphan_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Separation invariants — the load-bearing tests
# ─────────────────────────────────────────────────────────────────────────────

def test_scale_recompute_leaves_economics_snapshots_untouched(writable_db):
    """Invariant (a): running scale does NOT modify any
    trip_economics_snapshots row."""
    db, _rid = writable_db
    before = _select(
        db,
        "SELECT trip_id, transform_run_id, domain_name, estimated_revenue, "
        "       estimated_profit, estimated_operational_cost "
        "  FROM trip_economics_snapshots ORDER BY trip_id, transform_run_id"
    )
    scale.run(db, scale_model="urban_dense_fleet")
    scale.run(db, scale_model="national_scale")
    after = _select(
        db,
        "SELECT trip_id, transform_run_id, domain_name, estimated_revenue, "
        "       estimated_profit, estimated_operational_cost "
        "  FROM trip_economics_snapshots ORDER BY trip_id, transform_run_id"
    )
    assert before == after


def test_scale_recompute_leaves_telemetry_trips_events_untouched(writable_db):
    """Invariant (b): scale never touches telemetry, trips, or events."""
    db, _rid = writable_db
    tables = ("telemetry_observations", "trips", "delivery_events")
    before = {
        t: _select(db, f"SELECT * FROM {t} ORDER BY 1") for t in tables
    }
    scale.run(db, scale_model="regional_network")
    scale.run(db, scale_model="national_scale")
    after = {
        t: _select(db, f"SELECT * FROM {t} ORDER BY 1") for t in tables
    }
    for t in tables:
        assert before[t] == after[t], f"{t} mutated by scale transform"


def test_same_amortization_for_same_fleet_size_and_overhead(writable_db):
    """Invariant (c): two ScaleModels that differ only in
    utilization_efficiency (the *rebate* knob) produce the same
    amortized_overhead_per_trip, because amortization depends only on
    overhead $/day and deliveries_per_day.
    """
    db, _rid = writable_db
    base = get_scale_model("regional_network")
    a = replace(base, name="_test_a", utilization_efficiency=0.30)
    b = replace(base, name="_test_b", utilization_efficiency=0.80)
    scale.run(db, scale_model=a)
    scale.run(db, scale_model=b)
    over_a = dict(_select(
        db,
        "SELECT trip_id, amortized_overhead_per_trip "
        "FROM trip_scale_snapshots WHERE scale_model_name = '_test_a'"
    ))
    over_b = dict(_select(
        db,
        "SELECT trip_id, amortized_overhead_per_trip "
        "FROM trip_scale_snapshots WHERE scale_model_name = '_test_b'"
    ))
    assert over_a.keys() == over_b.keys()
    for tid in over_a:
        assert over_a[tid] == over_b[tid], (
            f"amortization differs for {tid} despite same overhead/fleet"
        )


def test_different_fleet_size_changes_overhead_not_op_cost(writable_db):
    """Invariant (d): two scale_models with different fleet_size produce
    different amortized overhead per trip, but the underlying
    trip_economics_snapshots.estimated_operational_cost is unchanged."""
    db, _rid = writable_db
    op_costs_before = dict(_select(
        db,
        "SELECT trip_id, estimated_operational_cost "
        "FROM trip_economics_snapshots"
    ))
    scale.run(db, scale_model="pilot_program")
    scale.run(db, scale_model="national_scale")
    overhead_pilot = dict(_select(
        db,
        "SELECT trip_id, amortized_overhead_per_trip "
        "FROM trip_scale_snapshots WHERE scale_model_name = 'pilot_program' "
        "  AND transform_run_id = (SELECT transform_run_id "
        "    FROM trip_scale_snapshots WHERE scale_model_name='pilot_program' "
        "    ORDER BY created_at DESC LIMIT 1)"
    ))
    overhead_nat = dict(_select(
        db,
        "SELECT trip_id, amortized_overhead_per_trip "
        "FROM trip_scale_snapshots WHERE scale_model_name = 'national_scale'"
    ))
    op_costs_after = dict(_select(
        db,
        "SELECT trip_id, estimated_operational_cost "
        "FROM trip_economics_snapshots"
    ))
    # Overhead differs.
    for tid in overhead_pilot:
        assert overhead_pilot[tid] != overhead_nat[tid], (
            f"overhead identical between pilot and national for {tid}"
        )
    # Operational cost unchanged.
    assert op_costs_before == op_costs_after


def test_scale_recompute_is_idempotent(writable_db):
    """Invariant (e): two consecutive recomputes of the same scale
    model produce identical numbers in the latest row per trip."""
    db, _rid = writable_db
    scale.run(db, scale_model="regional_network")
    a = dict(_select(
        db,
        """
        WITH r AS (
            SELECT trip_id, effective_profit, amortized_overhead_per_trip,
                   ROW_NUMBER() OVER (PARTITION BY trip_id
                                      ORDER BY created_at DESC) rk
              FROM trip_scale_snapshots WHERE scale_model_name='regional_network'
        )
        SELECT trip_id, effective_profit FROM r WHERE rk = 1 ORDER BY trip_id
        """
    ))
    scale.run(db, scale_model="regional_network")
    b = dict(_select(
        db,
        """
        WITH r AS (
            SELECT trip_id, effective_profit, amortized_overhead_per_trip,
                   ROW_NUMBER() OVER (PARTITION BY trip_id
                                      ORDER BY created_at DESC) rk
              FROM trip_scale_snapshots WHERE scale_model_name='regional_network'
        )
        SELECT trip_id, effective_profit FROM r WHERE rk = 1 ORDER BY trip_id
        """
    ))
    assert a == b


def test_two_domains_x_one_scale_produces_2n_rows(writable_db):
    """Invariant (f): scale rows are pure-additive — applying scale to
    two different economics snapshots produces 2 × n_trips total rows.
    """
    db, _rid = writable_db
    # Add a second economics recompute under food_delivery so we have
    # two distinct source snapshots to amortize over.
    economics.run(db, delivery_domain="food_delivery")
    n_trips = _select(db, "SELECT COUNT(*) FROM trips")[0][0]
    # Wipe pre-existing scale rows to simplify the count.
    conn = sqlite3.connect(db)
    try:
        conn.execute("DELETE FROM trip_scale_snapshots")
        conn.commit()
    finally:
        conn.close()
    # Amortize over each source explicitly.
    sources = [r[0] for r in _select(
        db, "SELECT DISTINCT transform_run_id FROM trip_economics_snapshots"
    )]
    assert len(sources) == 2
    for src in sources:
        scale.run(db, scale_model="regional_network", source_snapshot_run_id=src)
    total = _select(
        db, "SELECT COUNT(*) FROM trip_scale_snapshots"
    )[0][0]
    assert total == 2 * n_trips


# ─────────────────────────────────────────────────────────────────────────────
# Effective-profit math
# ─────────────────────────────────────────────────────────────────────────────

def test_effective_profit_formula_matches_inputs(writable_db):
    """Sanity: pick one trip, compute the expected effective_profit by
    hand from the source economics + scale knobs, and verify the row
    matches.  Catches accidental sign flips / formula drift."""
    db, _rid = writable_db
    scale.run(db, scale_model="urban_dense_fleet")
    sm = get_scale_model("urban_dense_fleet")
    rows = _select(
        db,
        """
        SELECT s.trip_id, s.effective_profit,
               s.amortized_overhead_per_trip,
               e.estimated_profit, e.estimated_operational_cost
          FROM trip_scale_snapshots s
          JOIN trip_economics_snapshots e
               ON e.transform_run_id = s.source_snapshot_run_id
              AND e.trip_id          = s.trip_id
         WHERE s.scale_model_name = 'urban_dense_fleet'
         LIMIT 1
        """
    )
    assert rows, "no urban_dense_fleet row to check"
    trip_id, eff, overhead, src_profit, src_op_cost = rows[0]
    # Recompute by hand:
    expected_overhead = sm.amortized_overhead_per_trip()
    expected_rebate   = sm.utilization_efficiency * sm.idle_reduction_factor * src_op_cost
    expected_eff      = round(src_profit - expected_overhead + expected_rebate, 4)
    assert round(overhead, 4) == round(expected_overhead, 4)
    assert round(eff, 2)      == round(expected_eff, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Analytics SQL + chart + API
# ─────────────────────────────────────────────────────────────────────────────

def test_scale_comparison_sql_runs(writable_db):
    db, _rid = writable_db
    scale.run(db, scale_model="urban_dense_fleet")
    sql = Path("analytics/sql/scale_model_comparison.sql").read_text(encoding="utf-8")
    rows = _select(db, sql)
    assert rows
    scale_names = {r[0] for r in rows}
    assert {"pilot_program", "urban_dense_fleet"}.issubset(scale_names)


@pytest.mark.slow
def test_cost_per_delivery_chart_renders(writable_db, tmp_path: Path):
    from core.visualizations import generate_charts
    db, _rid = writable_db
    scale.run(db, scale_model="regional_network")
    scale.run(db, scale_model="urban_dense_fleet")
    paths = generate_charts(db_path=db, out_dir=str(tmp_path / "charts"))
    p = Path(paths["cost_per_delivery_by_scale"])
    assert p.exists()
    assert p.stat().st_size > 0


@pytest.mark.slow
def test_api_scale_models_endpoint(writable_db):
    from fastapi.testclient import TestClient
    db, _rid = writable_db
    scale.run(db, scale_model="regional_network")
    scale.run(db, scale_model="urban_dense_fleet")
    old = os.environ.get("DRONE_API_DB")
    os.environ["DRONE_API_DB"] = db
    try:
        from api.main import app
        client = TestClient(app)
        body = client.get("/analytics/scale-models").json()
    finally:
        if old is None: del os.environ["DRONE_API_DB"]
        else:           os.environ["DRONE_API_DB"] = old
    assert body["registry_version"] == SCALE_MODEL_REGISTRY_VERSION
    assert len(body["profiles"]) == 4
    seen = {s["scale_model_name"] for s in body["latest_snapshots"]}
    assert {"pilot_program", "regional_network", "urban_dense_fleet"}.issubset(seen)
