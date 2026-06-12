"""Phase 33: multi-domain service mixes — registry + split-volume analysis."""

from __future__ import annotations

import pytest

from transforms import economics
from core.service_mixes import (
    ServiceMix, ServiceMixComponent,
    get_service_mix, iter_service_mixes, list_service_mixes,
)
from core.service_mix_analysis import (
    best_worst_service_mix, compute_service_mix_summary,
)


# ── Registry / validation ───────────────────────────────────────────────────

def test_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to"):
        ServiceMix(name="bad", description="", components=(
            ServiceMixComponent("urgent_documents", 0.6),
            ServiceMixComponent("medical_delivery", 0.3),  # sums to 0.9
        ))


def test_duplicate_component_domain_raises():
    with pytest.raises(ValueError, match="duplicate"):
        ServiceMix(name="dup", description="", components=(
            ServiceMixComponent("medical_delivery", 0.5),
            ServiceMixComponent("medical_delivery", 0.5),
        ))


def test_unknown_component_domain_raises():
    with pytest.raises(KeyError):
        ServiceMix(name="unk", description="", components=(
            ServiceMixComponent("not_a_domain", 1.0),
        ))


def test_non_positive_weight_raises():
    with pytest.raises(ValueError, match="non-positive"):
        ServiceMix(name="neg", description="", components=(
            ServiceMixComponent("medical_delivery", 1.5),
            ServiceMixComponent("retail_package", -0.5),
        ))


def test_reserved_character_in_name_raises():
    with pytest.raises(ValueError, match="reserved"):
        ServiceMix(name="bad@name", description="", components=(
            ServiceMixComponent("medical_delivery", 1.0),
        ))


def test_list_includes_builtins():
    names = list_service_mixes()
    for expected in ("urgent_medical_courier", "pharmacy_courier",
                     "local_courier_mix", "platform_mixed_local"):
        assert expected in names


def test_get_returns_expected_components():
    mix = get_service_mix("urgent_medical_courier")
    by_domain = {c.delivery_domain: c.weight for c in mix.components}
    assert by_domain == {"urgent_documents": 0.60, "medical_delivery": 0.40}


def test_iter_yields_all():
    assert {m.name for m in iter_service_mixes()} == set(list_service_mixes())


# ── Analysis (split-volume) ─────────────────────────────────────────────────

@pytest.fixture
def mix_db(writable_db) -> str:
    """A DB with economics snapshots for every domain the built-in mixes use."""
    db, _rid = writable_db
    for dom in ("food_delivery", "medical_delivery", "urgent_documents"):
        economics.run(db, delivery_domain=dom)
    # retail_package is the default — already present from the writable_db run.
    return db


def test_analysis_returns_rows_for_default_mixes(mix_db: str):
    rows = compute_service_mix_summary(mix_db)
    assert rows
    assert {r["service_mix_name"] for r in rows} <= set(list_service_mixes())


def test_rows_include_component_details(mix_db: str):
    rows = compute_service_mix_summary(
        mix_db, service_mix_names=["urgent_medical_courier"],
        deliveries_per_day_values=[1000],
    )
    assert rows
    r = rows[0]
    assert r["component_count"] == 2
    for c in r["components"]:
        for k in ("component_domain", "mix_weight", "component_effective_profit",
                  "weighted_effective_profit", "component_source_profit",
                  "component_operational_cost", "component_revenue",
                  "component_domain_response", "component_volume"):
            assert k in c


def test_split_volume_uses_component_share(mix_db: str):
    """A mix at total 1000 with 60/40 weights serves the components at
    600 and 400 — NOT 1000 each."""
    rows = compute_service_mix_summary(
        mix_db, service_mix_names=["urgent_medical_courier"],
        deliveries_per_day_values=[1000],
    )
    comps = {c["component_domain"]: c for c in rows[0]["components"]}
    assert comps["urgent_documents"]["component_volume"] == 600
    assert comps["medical_delivery"]["component_volume"] == 400


def test_weighted_effective_profit_matches_blend(mix_db: str):
    """avg_effective_profit must equal Σ weighted_effective_profit."""
    for r in compute_service_mix_summary(mix_db, deliveries_per_day_values=[1000]):
        blended = sum(c["weighted_effective_profit"] for c in r["components"])
        assert r["avg_effective_profit"] == pytest.approx(blended, abs=1e-2)


def test_capacity_overhead_is_single_shared_value(mix_db: str):
    """The mix carries ONE shared overhead, not a per-component average —
    and it equals the overhead for the full total volume."""
    from core.volume_sensitivity import capacity_overhead_per_delivery
    from core.volume_sensitivity import DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY
    rows = compute_service_mix_summary(
        mix_db, service_mix_names=["urgent_medical_courier"],
        deliveries_per_day_values=[1000],
    )
    r = rows[0]
    expected = capacity_overhead_per_delivery(
        DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY, 1000)
    assert r["capacity_overhead_per_delivery"] == pytest.approx(expected, abs=1e-2)


def test_best_worst_component_match_extremes(mix_db: str):
    for r in compute_service_mix_summary(mix_db, deliveries_per_day_values=[1000]):
        effs = {c["component_domain"]: c["component_effective_profit"]
                for c in r["components"]}
        best = max(effs, key=effs.get)
        worst = min(effs, key=effs.get)
        assert r["best_component_domain"] == best
        assert r["worst_component_domain"] == worst


def test_best_worst_summary_shape(mix_db: str):
    bw = best_worst_service_mix(mix_db)
    assert bw["best"] and bw["worst"]
    for r in bw["rows"]:
        assert "beats_weakest_component" in r
        assert "weakest_component_effective_profit" in r


def test_immutability(mix_db: str):
    """Analysis must not write to economics snapshots."""
    import sqlite3, hashlib
    def digest():
        conn = sqlite3.connect(mix_db)
        try:
            h = hashlib.sha256()
            for row in conn.execute(
                "SELECT * FROM trip_economics_snapshots ORDER BY rowid"):
                h.update(repr(row).encode())
        finally:
            conn.close()
        return h.hexdigest()
    before = digest()
    compute_service_mix_summary(mix_db, deliveries_per_day_values=[500, 1000])
    assert digest() == before


# ── API endpoint ────────────────────────────────────────────────────────────

def test_api_service_mixes_endpoint(mix_db: str):
    import os
    from fastapi.testclient import TestClient
    old = os.environ.get("DRONE_API_DB")
    os.environ["DRONE_API_DB"] = mix_db
    try:
        from api.main import app
        body = TestClient(app).get("/analytics/service-mixes").json()
    finally:
        if old is None: del os.environ["DRONE_API_DB"]
        else:           os.environ["DRONE_API_DB"] = old
    for k in ("rows", "service_mixes", "capacity_models",
              "default_capacity_model", "caveats"):
        assert k in body
    assert body["service_mixes"]
    assert body["service_mixes"][0]["components"]


@pytest.mark.slow
def test_service_mix_chart_renders(mix_db: str, tmp_path):
    from core.visualizations import generate_charts
    paths = generate_charts(db_path=mix_db, out_dir=str(tmp_path))
    import os
    p = paths["service_mix_profit_by_volume"]
    assert os.path.exists(p) and os.path.getsize(p) > 0
