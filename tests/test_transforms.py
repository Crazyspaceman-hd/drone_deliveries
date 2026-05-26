"""Phase 20: transform layer — recomputability, lineage, parameter overrides."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.economic_models import EconomicModel, from_scenario_name
from transforms import economics, hybrid
from transforms.hybrid import HybridThresholds
from transforms.runner import run_pipeline


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
# raw_db renamed → writable_raw_db (conftest.py session fixture + copy).
# No local fixture needed; conftest supplies it.

def _derived_columns_nulls(db_path: str) -> tuple[int, int]:
    """Return (orders_null_fulfillment, trips_null_profit) counts."""
    conn = sqlite3.connect(db_path)
    try:
        a = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE fulfillment_mode IS NULL"
        ).fetchone()[0]
        b = conn.execute(
            "SELECT COUNT(*) FROM trips WHERE estimated_profit IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    return a, b


# ─────────────────────────────────────────────────────────────────────────────
# Simulator now emits raw operational events only
# ─────────────────────────────────────────────────────────────────────────────

def test_simulator_leaves_derived_columns_null(writable_raw_db: tuple[str, str]):
    db_path, _rid = writable_raw_db
    null_orders, null_trips = _derived_columns_nulls(db_path)
    # Every order should have NULL fulfillment_mode until the hybrid
    # transform runs, and every trip should have NULL estimated_profit
    # until the economics transform runs.
    assert null_orders == 10
    assert null_trips  == 10


# ─────────────────────────────────────────────────────────────────────────────
# Transforms populate the columns
# ─────────────────────────────────────────────────────────────────────────────

def test_economics_transform_populates_trip_columns(writable_raw_db: tuple[str, str]):
    db_path, rid = writable_raw_db
    res = economics.run(db_path, run_id=rid)
    assert res["transform_name"] == "economics"
    assert res["rows_updated"]   == 10
    _, null_trips = _derived_columns_nulls(db_path)
    assert null_trips == 0


def test_hybrid_transform_populates_order_columns(writable_raw_db: tuple[str, str]):
    db_path, rid = writable_raw_db
    # Run economics first so trip_distance_km is set (hybrid uses it).
    economics.run(db_path, run_id=rid)
    res = hybrid.run(db_path, run_id=rid)
    assert res["rows_updated"] == 10
    null_orders, _ = _derived_columns_nulls(db_path)
    assert null_orders == 0


def test_pipeline_in_order_works(writable_raw_db: tuple[str, str]):
    db_path, rid = writable_raw_db
    results = run_pipeline(db_path, run_id=rid)
    # Auto-discovered pipeline:
    #   Phase 21: economics(10) → hybrid(20) → telemetry(30)
    #   Phase 23: economics(10) → scale(15) → hybrid(20) → telemetry(30)
    # Asserting the *relative* ordering (RUN_ORDER ascending) so adding
    # another transform doesn't break this contract.
    names = [r["transform_name"] for r in results]
    assert names[0] == "economics"     # RUN_ORDER 10
    assert names[-1] == "telemetry"    # RUN_ORDER 30 (highest)
    assert "scale" in names            # RUN_ORDER 15
    assert "hybrid" in names           # RUN_ORDER 20
    # scale must run before hybrid (RUN_ORDER 15 < 20).
    assert names.index("scale") < names.index("hybrid")
    null_orders, null_trips = _derived_columns_nulls(db_path)
    assert null_orders == 0 and null_trips == 0


# ─────────────────────────────────────────────────────────────────────────────
# Transforms are rerunnable — re-running produces the same numbers
# ─────────────────────────────────────────────────────────────────────────────

def test_economics_idempotent(writable_raw_db: tuple[str, str]):
    db_path, rid = writable_raw_db
    economics.run(db_path, run_id=rid)
    conn = sqlite3.connect(db_path)
    try:
        before = conn.execute(
            "SELECT trip_id, estimated_profit FROM trips ORDER BY trip_id"
        ).fetchall()
    finally:
        conn.close()
    economics.run(db_path, run_id=rid)
    conn = sqlite3.connect(db_path)
    try:
        after = conn.execute(
            "SELECT trip_id, estimated_profit FROM trips ORDER BY trip_id"
        ).fetchall()
    finally:
        conn.close()
    assert before == after


# ─────────────────────────────────────────────────────────────────────────────
# Parameter overrides change outputs without rerunning the simulator
# ─────────────────────────────────────────────────────────────────────────────

def test_economic_model_override_changes_revenue_only(writable_raw_db: tuple[str, str]):
    """Phase 22 update: revenue = delivery_fee + premium_uplift + aov_uplift,
    where premium_uplift = delivery_fee × premium_share × 0.5 (default
    retail_package: premium_share=0.08).  A +$100 delivery_fee bump
    therefore changes revenue by 100 × (1 + 0.08 × 0.5) = +$104 per
    completed trip.  Aborted trips are unaffected (revenue = 0)."""
    from core.delivery_domains import get_domain
    db_path, rid = writable_raw_db
    economics.run(db_path, run_id=rid)
    base = _trip_profits(db_path)

    sc_model = from_scenario_name("suburban_standard")
    high_fee = EconomicModel(
        **{**sc_model.__dict__, "delivery_fee": sc_model.delivery_fee + 100.0,
           "name": "suburban_high_fee"},
    )
    economics.run(db_path, run_id=rid, model=high_fee)
    after = _trip_profits(db_path)

    # Compute the expected delta from the default-domain premium share.
    default_domain = get_domain(None)
    expected_delta = round(100.0 * (1.0 + default_domain.premium_share * 0.5), 2)
    for trip_id, status, before_profit in base:
        if status != "completed":
            continue
        after_profit = next(a for tid, _, a in after if tid == trip_id)
        assert round(after_profit - before_profit, 2) == expected_delta


def test_hybrid_threshold_override_changes_mode_split(writable_raw_db: tuple[str, str]):
    db_path, rid = writable_raw_db
    run_pipeline(db_path, run_id=rid)
    baseline_modes = _mode_counts(db_path)
    # Make EVERYTHING heavy_payload-eligible by raising the threshold so
    # nothing trips the truck disqualifier.  Lower light_payload too so
    # most orders become drone-eligible.
    th = HybridThresholds(heavy_payload_kg=999.0, light_payload_kg=999.0)
    hybrid.run(db_path, run_id=rid, thresholds=th)
    skewed = _mode_counts(db_path)
    # The split must differ.
    assert baseline_modes != skewed


# ─────────────────────────────────────────────────────────────────────────────
# Lineage
# ─────────────────────────────────────────────────────────────────────────────

def test_transformation_runs_rows_created(writable_raw_db: tuple[str, str]):
    db_path, rid = writable_raw_db
    run_pipeline(db_path, run_id=rid)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT transform_name, transform_version, source_run_id, row_count "
            "  FROM transformation_runs ORDER BY created_at ASC"
        ).fetchall()
    finally:
        conn.close()
    names = [r[0] for r in rows]
    assert "economics" in names
    assert "hybrid"    in names
    # Phase 21: telemetry transform's row_count is per (run, scenario),
    # not per order/trip — so we assert per-transform shapes explicitly.
    expected_row_count = {
        "economics": 10,   # one per trip
        "hybrid":    10,   # one per order
        "telemetry":  1,   # one per (run, scenario); one scenario per run here
    }
    for name, _ver, src, row_count in rows:
        assert src == rid
        if name in expected_row_count:
            assert row_count == expected_row_count[name], (
                f"{name}: row_count={row_count}, expected={expected_row_count[name]}"
            )


def test_transformation_runs_parameters_json_captured(writable_raw_db: tuple[str, str]):
    """When a model override is supplied, its JSON is persisted."""
    db_path, rid = writable_raw_db
    sc = from_scenario_name("urban_dense")
    model = EconomicModel(**{**sc.__dict__, "name": "urban_dense_high_fee",
                             "delivery_fee": 99.0})
    economics.run(db_path, run_id=rid, model=model)
    conn = sqlite3.connect(db_path)
    try:
        params_json = conn.execute(
            "SELECT parameters_json FROM transformation_runs "
            "WHERE transform_name = 'economics' "
            " ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()
    # Phase 22: parameters_json now captures the model NAME plus domain
    # + registry version, not the full EconomicModel serialization.
    # Check the model name flows through; the underlying delivery_fee
    # value lives in the EconomicModel registry, not the params_json.
    assert params_json and "urban_dense_high_fee" in params_json


# ─────────────────────────────────────────────────────────────────────────────
# Behavioral invariants (Phase 20): prefer these over exact-count assertions
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant_no_negative_profit_inputs(writable_raw_db: tuple[str, str]):
    """After economics transform: revenue, op_cost, distance all >= 0."""
    db_path, rid = writable_raw_db
    economics.run(db_path, run_id=rid)
    conn = sqlite3.connect(db_path)
    try:
        bad = conn.execute(
            "SELECT trip_id FROM trips "
            " WHERE estimated_revenue < 0 "
            "    OR estimated_operational_cost < 0 "
            "    OR trip_distance_km < 0"
        ).fetchall()
    finally:
        conn.close()
    assert not bad


def test_invariant_latency_ordering_completed_trips(writable_raw_db: tuple[str, str]):
    """After hybrid transform: drones-only avg latency < trucks-only.

    This is the 'hybrid is faster' invariant the project is structured to
    prove.  Tests it as a *behavior*, not an exact number.
    """
    db_path, rid = writable_raw_db
    run_pipeline(db_path, run_id=rid)
    conn = sqlite3.connect(db_path)
    try:
        truck_avg, drone_avg = conn.execute(
            "SELECT AVG(truck_baseline_latency_min), "
            "       AVG(drone_estimated_latency_min) FROM orders"
        ).fetchone()
    finally:
        conn.close()
    assert drone_avg < truck_avg


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _trip_profits(db_path: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT trip_id, status, estimated_profit FROM trips ORDER BY trip_id"
        ).fetchall()
    finally:
        conn.close()


def _mode_counts(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute(
            "SELECT fulfillment_mode, COUNT(*) FROM orders GROUP BY fulfillment_mode"
        ).fetchall())
    finally:
        conn.close()
