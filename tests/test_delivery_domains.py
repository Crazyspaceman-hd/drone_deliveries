"""Phase 22: delivery-domain reinterpretation + snapshot table.

Most tests are *separation invariants* — they check that the domain
overlay influences only revenue/profit and does not leak into physics
fields (distance, energy cost, maintenance cost, telemetry).  The
weaker "domain change changes revenue" variant is true by construction
and intentionally absent.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from dataclasses import replace

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # so `baselines` resolves

from core.delivery_domains import (
    DELIVERY_DOMAIN_REGISTRY_VERSION, DEFAULT_DOMAIN_NAME, DeliveryDomain,
    get_domain, list_domains,
)
from transforms import economics


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

# writable_db removed — use conftest.py writable_db instead.

def _select_one(db_path: str, sql: str, params: tuple = ()) -> tuple:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _select_all(db_path: str, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Registry smoke checks
# ─────────────────────────────────────────────────────────────────────────────

def test_registry_contains_four_builtins():
    assert set(list_domains()) == {
        "food_delivery", "medical_delivery",
        "retail_package", "urgent_documents",
    }


def test_default_domain_is_retail_package():
    assert DEFAULT_DOMAIN_NAME == "retail_package"
    assert get_domain(None).name == DEFAULT_DOMAIN_NAME


def test_unknown_domain_raises():
    with pytest.raises(KeyError):
        get_domain("does_not_exist")


def test_get_domain_passes_through_instance():
    food = get_domain("food_delivery")
    assert get_domain(food) is food


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot table semantics
# ─────────────────────────────────────────────────────────────────────────────

def test_default_recompute_writes_snapshot_row_per_trip(writable_db):
    db, _rid = writable_db
    rows = _select_all(
        db, "SELECT trip_id, domain_name FROM trip_economics_snapshots"
    )
    # Auto-run during run_simulation = one snapshot row per trip with
    # domain_name = retail_package.
    n_trips = _select_one(db, "SELECT COUNT(*) FROM trips")[0]
    assert len(rows) == n_trips
    assert {r[1] for r in rows} == {"retail_package"}


def test_two_domains_produce_two_snapshots_per_trip(writable_db):
    db, _rid = writable_db
    economics.run(db, delivery_domain="food_delivery")
    n_trips = _select_one(db, "SELECT COUNT(*) FROM trips")[0]
    per_trip = _select_all(
        db,
        "SELECT trip_id, COUNT(*) FROM trip_economics_snapshots GROUP BY trip_id",
    )
    assert len(per_trip) == n_trips
    for _trip_id, n in per_trip:
        assert n == 2   # default (retail_package) + food_delivery


def test_trips_estimated_profit_reflects_most_recent_recompute(writable_db):
    db, _rid = writable_db
    # Recompute under food_delivery; trips.estimated_profit must change to
    # reflect the new domain, while the prior retail_package snapshot
    # survives in the history table.
    before = _select_all(
        db, "SELECT trip_id, estimated_profit FROM trips ORDER BY trip_id"
    )
    economics.run(db, delivery_domain="food_delivery")
    after = _select_all(
        db, "SELECT trip_id, estimated_profit FROM trips ORDER BY trip_id"
    )
    assert before != after, "trips.estimated_profit should reflect newest run"
    # And the retail_package snapshot is still in history.
    history = _select_all(
        db,
        "SELECT DISTINCT domain_name FROM trip_economics_snapshots ORDER BY domain_name",
    )
    assert {r[0] for r in history} == {"food_delivery", "retail_package"}


# ─────────────────────────────────────────────────────────────────────────────
# Lineage
# ─────────────────────────────────────────────────────────────────────────────

def test_parameters_json_captures_domain_and_registry_version(writable_db):
    db, _rid = writable_db
    economics.run(db, delivery_domain="medical_delivery")
    rows = _select_all(
        db,
        "SELECT parameters_json FROM transformation_runs "
        "WHERE transform_name = 'economics' ORDER BY created_at DESC LIMIT 1",
    )
    assert rows, "transformation_runs has no economics row"
    import json
    body = json.loads(rows[0][0])
    assert body["delivery_domain"]                       == "medical_delivery"
    assert body["registry_versions"]["delivery_domain"]  == DELIVERY_DOMAIN_REGISTRY_VERSION


def test_each_snapshot_resolves_to_its_transformation_run(writable_db):
    db, _rid = writable_db
    economics.run(db, delivery_domain="food_delivery")
    # Every snapshot's transform_run_id should be present in
    # transformation_runs — proves the lineage join works.
    orphans = _select_one(
        db,
        """
        SELECT COUNT(*) FROM trip_economics_snapshots s
         WHERE s.transform_run_id NOT IN
               (SELECT transform_run_id FROM transformation_runs)
        """,
    )[0]
    assert orphans == 0


# ─────────────────────────────────────────────────────────────────────────────
# Separation invariants — the load-bearing tests of this phase
# ─────────────────────────────────────────────────────────────────────────────

def test_domain_change_does_not_change_physics_fields(writable_db):
    """Changing the delivery domain MUST NOT shift any physics-side
    field (distance, energy cost, maintenance cost, operational cost,
    emergency penalty).  Revenue and profit are the only quantities the
    domain is allowed to move."""
    db, _rid = writable_db
    # Pull retail_package snapshots first (already populated by the
    # default recompute), then re-run under food_delivery and compare.
    retail = {
        t: (dist, energy, maint, op_cost, penalty)
        for t, dist, energy, maint, op_cost, penalty in _select_all(
            db,
            "SELECT trip_id, trip_distance_km, estimated_energy_cost, "
            "       estimated_maintenance_cost, estimated_operational_cost, "
            "       emergency_return_penalty_applied "
            "  FROM trip_economics_snapshots WHERE domain_name = 'retail_package'"
        )
    }
    economics.run(db, delivery_domain="food_delivery")
    food = {
        t: (dist, energy, maint, op_cost, penalty)
        for t, dist, energy, maint, op_cost, penalty in _select_all(
            db,
            "SELECT trip_id, trip_distance_km, estimated_energy_cost, "
            "       estimated_maintenance_cost, estimated_operational_cost, "
            "       emergency_return_penalty_applied "
            "  FROM trip_economics_snapshots WHERE domain_name = 'food_delivery'"
        )
    }
    assert retail.keys() == food.keys()
    for trip_id in retail:
        assert retail[trip_id] == food[trip_id], (
            f"physics field drift for {trip_id}: "
            f"retail={retail[trip_id]} food={food[trip_id]}"
        )


def test_two_domains_with_same_payload_mean_produce_same_energy_cost(writable_db):
    """Energy cost is per-trip distance × rate; domain.payload_kg_mean
    should not leak in.  Constructed proof: two synthetic domains with
    different premium / AOV but the same payload-mean produce identical
    estimated_energy_cost on every trip."""
    db, _rid = writable_db
    # Two ad-hoc domains: same physics-irrelevant payload mean, different
    # demand-side knobs.  Passing the DeliveryDomain instance directly so
    # we don't need to mutate the registry.
    base = get_domain("retail_package")
    dom_a = replace(base, name="_test_a", premium_share=0.10,
                    average_order_value_usd=20.0)
    dom_b = replace(base, name="_test_b", premium_share=0.90,
                    average_order_value_usd=200.0)
    economics.run(db, delivery_domain=dom_a)
    energy_a = dict(_select_all(
        db,
        "SELECT trip_id, estimated_energy_cost FROM trip_economics_snapshots "
        "WHERE domain_name = '_test_a'"
    ))
    economics.run(db, delivery_domain=dom_b)
    energy_b = dict(_select_all(
        db,
        "SELECT trip_id, estimated_energy_cost FROM trip_economics_snapshots "
        "WHERE domain_name = '_test_b'"
    ))
    assert energy_a.keys() == energy_b.keys()
    for trip_id in energy_a:
        assert energy_a[trip_id] == energy_b[trip_id], (
            f"energy cost differs for {trip_id} despite same payload mean"
        )


def test_domain_change_does_not_touch_telemetry(writable_db):
    """Telemetry rows are observations from the simulator's source layer.
    The economics transform must never write to them."""
    db, _rid = writable_db
    before = _select_all(
        db, "SELECT event_id, altitude_m, battery_temp_c, motor_temp_c "
            "FROM telemetry_observations ORDER BY event_id"
    )
    economics.run(db, delivery_domain="urgent_documents")
    after = _select_all(
        db, "SELECT event_id, altitude_m, battery_temp_c, motor_temp_c "
            "FROM telemetry_observations ORDER BY event_id"
    )
    assert before == after


def test_recompute_is_idempotent_for_same_domain(writable_db):
    """Recomputing the same domain twice yields identical snapshot
    numbers.  Two separate rows, same values."""
    db, _rid = writable_db
    economics.run(db, delivery_domain="food_delivery")
    a = {t: (r, p) for t, r, p in _select_all(
        db,
        "SELECT trip_id, estimated_revenue, estimated_profit "
        "FROM trip_economics_snapshots WHERE domain_name = 'food_delivery' "
        "ORDER BY trip_id"
    )}
    economics.run(db, delivery_domain="food_delivery")
    # Two food_delivery snapshots per trip now exist (different
    # transform_run_id); fetch the latest by created_at.
    rows = _select_all(
        db,
        """
        WITH r AS (
            SELECT trip_id, estimated_revenue, estimated_profit, created_at,
                   ROW_NUMBER() OVER (PARTITION BY trip_id
                                      ORDER BY created_at DESC) rk
              FROM trip_economics_snapshots WHERE domain_name = 'food_delivery'
        )
        SELECT trip_id, estimated_revenue, estimated_profit
          FROM r WHERE rk = 1 ORDER BY trip_id
        """
    )
    b = {t: (r, p) for t, r, p in rows}
    assert a == b


# ─────────────────────────────────────────────────────────────────────────────
# Analytics SQL + chart + API
# ─────────────────────────────────────────────────────────────────────────────

def test_snapshot_comparison_sql_runs(writable_db):
    db, _rid = writable_db
    economics.run(db, delivery_domain="food_delivery")
    sql = Path("analytics/sql/snapshot_comparison.sql").read_text(encoding="utf-8")
    rows = _select_all(db, sql)
    assert rows
    # Each trip should have at least two rows (retail_package + food_delivery).
    by_trip: dict[str, int] = {}
    for r in rows:
        by_trip[r[0]] = by_trip.get(r[0], 0) + 1
    assert all(n >= 2 for n in by_trip.values())


@pytest.mark.slow
def test_revenue_chart_renders(writable_db, tmp_path: Path):
    from core.visualizations import generate_charts
    db, _rid = writable_db
    economics.run(db, delivery_domain="food_delivery")
    economics.run(db, delivery_domain="medical_delivery")
    paths = generate_charts(db_path=db, out_dir=str(tmp_path / "charts"))
    p = Path(paths["revenue_by_delivery_domain"])
    assert p.exists()
    assert p.stat().st_size > 0


def test_api_delivery_domains_endpoint(writable_db):
    from fastapi.testclient import TestClient
    import os
    db, _rid = writable_db
    economics.run(db, delivery_domain="food_delivery")
    economics.run(db, delivery_domain="medical_delivery")
    old = os.environ.get("DRONE_API_DB")
    os.environ["DRONE_API_DB"] = db
    try:
        from api.main import app
        client = TestClient(app)
        body = client.get("/analytics/delivery-domains").json()
    finally:
        if old is None: del os.environ["DRONE_API_DB"]
        else:           os.environ["DRONE_API_DB"] = old
    assert body["registry_version"] == DELIVERY_DOMAIN_REGISTRY_VERSION
    assert len(body["profiles"]) == 4
    seen = {s["domain_name"] for s in body["latest_snapshots"]}
    assert {"food_delivery", "medical_delivery", "retail_package"}.issubset(seen)
