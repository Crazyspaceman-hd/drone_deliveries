"""Phase 28: capacity-coupled volume sensitivity.

The primary suite asserts structural and monotonic properties of the
capacity-coupled formula.  A small block at the bottom confirms the
Phase 27 ``legacy_fixed_overhead_sensitivity`` predecessor still works
exactly as before — it's preserved for chart-artifact compatibility.

We deliberately do NOT assert which delivery domain "wins" or that any
sweep point is profitable.  Those are project-thesis claims, not
properties of the math.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3

import pytest

from dataclasses import replace

from transforms import economics
from core.capacity_models    import get_capacity_model, list_capacity_models
from core.delivery_domains   import get_domain
from core.volume_sensitivity import (
    DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY,
    DEFAULT_DELIVERIES_PER_DAY_SWEEP,
    domain_efficiency_credit,
    domain_value_decay,
    legacy_fixed_overhead_sensitivity,
    legacy_sensitivity_metadata,
    sensitivity_metadata,
    volume_sensitivity,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: a DB with snapshots under at least two domains so per-domain
# rows actually appear.  Builds on the session-scoped writable_db.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def domain_populated_db(writable_db) -> str:
    db, _rid = writable_db
    # Default recompute already wrote retail_package snapshots; add food
    # so we have multiple domains to draw curves for.
    economics.run(db, delivery_domain="food_delivery")
    return db


# ═════════════════════════════════════════════════════════════════════════════
# Capacity-coupled (Phase 28 — primary)
# ═════════════════════════════════════════════════════════════════════════════

# ── Shape ───────────────────────────────────────────────────────────────────

def test_sensitivity_rows_non_empty(domain_populated_db: str):
    assert volume_sensitivity(domain_populated_db), "no rows returned"


def test_sweep_uses_at_least_ten_points(domain_populated_db: str):
    rows = volume_sensitivity(domain_populated_db)
    by_domain: dict[str, list[int]] = {}
    for r in rows:
        by_domain.setdefault(r["delivery_domain"], []).append(r["deliveries_per_day"])
    for domain, points in by_domain.items():
        assert len(points) >= 10, f"{domain}: only {len(points)} sweep points"


def test_deliveries_per_day_sorted_ascending_per_domain(domain_populated_db: str):
    rows = volume_sensitivity(domain_populated_db)
    by_domain: dict[str, list[int]] = {}
    for r in rows:
        by_domain.setdefault(r["delivery_domain"], []).append(r["deliveries_per_day"])
    for domain, points in by_domain.items():
        assert points == sorted(points), f"{domain} not sorted: {points}"


def test_default_sweep_matches_module_constant(domain_populated_db: str):
    rows = volume_sensitivity(domain_populated_db)
    a_domain = rows[0]["delivery_domain"]
    points = [r["deliveries_per_day"] for r in rows if r["delivery_domain"] == a_domain]
    assert points == DEFAULT_DELIVERIES_PER_DAY_SWEEP


def test_row_shape_includes_required_capacity_keys(domain_populated_db: str):
    rows = volume_sensitivity(domain_populated_db)
    expected = {
        "delivery_domain", "capacity_model", "deliveries_per_day",
        "required_drones", "required_operators",
        "required_maintenance_staff", "required_chargers",
        "daily_capacity_overhead", "capacity_overhead_per_delivery",
        "avg_operational_cost", "avg_revenue", "avg_source_profit",
        # Phase 29 response fields:
        "saturation_volume_per_day",
        "domain_efficiency_credit", "domain_value_decay",
        "net_domain_response",
        "adjusted_avg_operational_cost", "adjusted_avg_revenue",
        # Phase 29 revision: addressable-demand flag
        "within_addressable_demand",
        # Composite:
        "avg_effective_profit", "break_even_rate", "trip_count",
    }
    for r in rows:
        missing = expected - set(r.keys())
        assert not missing, f"missing keys: {missing}"


def test_required_capacity_fields_are_integers(domain_populated_db: str):
    """ceil() of integer math should produce ints — JSON serialization
    relies on this not being numpy floats etc."""
    for r in volume_sensitivity(domain_populated_db):
        for k in ("required_drones", "required_operators",
                  "required_maintenance_staff", "required_chargers"):
            assert isinstance(r[k], int), f"{k} = {r[k]} ({type(r[k]).__name__})"


# ── Capacity formula invariants ─────────────────────────────────────────────

def test_required_drones_non_decreasing_across_sweep(domain_populated_db: str):
    """Demand monotonically grows → required drones cannot drop.  Staircase
    flat steps are OK; what would be a bug is a strict decrease."""
    rows = volume_sensitivity(domain_populated_db)
    by_domain: dict[str, list[tuple[int, int]]] = {}
    for r in rows:
        by_domain.setdefault(r["delivery_domain"], []).append(
            (r["deliveries_per_day"], r["required_drones"])
        )
    for domain, series in by_domain.items():
        series.sort()
        for (d_low, n_low), (d_high, n_high) in zip(series, series[1:]):
            assert n_high >= n_low, (
                f"{domain}: drones decreased from d={d_low} (n={n_low}) "
                f"to d={d_high} (n={n_high})"
            )


def test_drone_capacity_meets_demand_at_every_sweep_point(domain_populated_db: str):
    """required_drones × deliveries_per_drone_per_day must ≥ deliveries_per_day.
    If this ever fails the model has under-provisioned and the row is
    economically meaningless."""
    rows = volume_sensitivity(domain_populated_db)
    cm   = get_capacity_model(DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY)
    for r in rows:
        cap_total = r["required_drones"] * cm.deliveries_per_drone_per_day
        assert cap_total >= r["deliveries_per_day"], (
            f"d={r['deliveries_per_day']}: drones={r['required_drones']} × "
            f"{cm.deliveries_per_drone_per_day}/drone/day = {cap_total} "
            f"< demand {r['deliveries_per_day']}"
        )


def test_daily_overhead_non_decreasing_with_volume(domain_populated_db: str):
    """More demand → more required drones → more daily overhead.  Flat
    steps OK (no new capacity tier crossed), strict drop is a bug."""
    rows = volume_sensitivity(domain_populated_db)
    by_domain: dict[str, list[tuple[int, float]]] = {}
    for r in rows:
        by_domain.setdefault(r["delivery_domain"], []).append(
            (r["deliveries_per_day"], r["daily_capacity_overhead"])
        )
    for domain, series in by_domain.items():
        series.sort()
        for (d_lo, oh_lo), (d_hi, oh_hi) in zip(series, series[1:]):
            assert oh_hi >= oh_lo, (
                f"{domain}: daily overhead fell from d={d_lo} (${oh_lo}) "
                f"to d={d_hi} (${oh_hi})"
            )


def test_overhead_per_delivery_does_not_collapse_to_zero(domain_populated_db: str):
    """The whole point of the Phase 28 correction.  Under the old
    fixed-overhead formula, overhead/delivery decays as 1/d toward zero.
    Under capacity-coupling, it has a floor: even at the highest sweep
    point you need at least one drone, and per-drone lease + minimum
    staffing creates a per-delivery overhead floor.

    Concretely: at d_max the overhead/delivery should still exceed
    (drone_lease_per_day / deliveries_per_drone_per_day) — i.e. the cost
    of leasing one drone amortized over what that drone can produce
    on its own.
    """
    rows = volume_sensitivity(domain_populated_db)
    cm   = get_capacity_model(DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY)
    floor = cm.drone_daily_lease_or_depreciation_usd / cm.deliveries_per_drone_per_day
    # At d_max, overhead/delivery must still be ≥ the per-drone amortized
    # lease floor.  (It will usually be much more because of platform +
    # staffing.)
    d_max = max(DEFAULT_DELIVERIES_PER_DAY_SWEEP)
    d_max_rows = [r for r in rows if r["deliveries_per_day"] == d_max]
    assert d_max_rows
    for r in d_max_rows:
        assert r["capacity_overhead_per_delivery"] >= floor * 0.99, (
            f"d={d_max}: overhead/delivery ${r['capacity_overhead_per_delivery']} "
            f"fell below per-drone lease floor ${floor:.2f}"
        )


def test_overhead_per_delivery_is_identical_across_domains_per_sweep_point(domain_populated_db: str):
    """Capacity overhead is a pure function of (capacity_model,
    deliveries_per_day); domain identity cannot leak in."""
    rows = volume_sensitivity(domain_populated_db)
    by_point: dict[int, set[float]] = {}
    for r in rows:
        by_point.setdefault(r["deliveries_per_day"], set()).add(
            round(r["capacity_overhead_per_delivery"], 6)
        )
    for d, values in by_point.items():
        assert len(values) == 1, (
            f"d={d}: overhead/delivery varied across domains: {values}"
        )


def test_effective_profit_changes_when_volume_changes(domain_populated_db: str):
    rows = volume_sensitivity(domain_populated_db)
    by_domain: dict[str, list[float]] = {}
    for r in rows:
        by_domain.setdefault(r["delivery_domain"], []).append(r["avg_effective_profit"])
    for domain, profits in by_domain.items():
        assert len(set(round(p, 2) for p in profits)) > 1, (
            f"{domain}: effective_profit flat across the sweep"
        )


def test_break_even_rate_bounded_unit_interval(domain_populated_db: str):
    for r in volume_sensitivity(domain_populated_db):
        assert 0.0 <= r["break_even_rate"] <= 1.0


# ── Parametrisation surface ─────────────────────────────────────────────────

def test_capacity_model_choice_changes_required_capacity(domain_populated_db: str):
    """Different productivity rates must produce different drone counts
    at the same demand."""
    pilot = volume_sensitivity(domain_populated_db, capacity_model="pilot_capacity")
    urban = volume_sensitivity(domain_populated_db, capacity_model="dense_urban_capacity")
    # d = 1000: pilot needs ceil(1000/8) = 125; dense_urban needs ceil(1000/30) = 34.
    p1000 = next(r for r in pilot if r["deliveries_per_day"] == 1000)
    u1000 = next(r for r in urban if r["deliveries_per_day"] == 1000)
    assert p1000["required_drones"] > u1000["required_drones"]
    assert p1000["capacity_overhead_per_delivery"] != u1000["capacity_overhead_per_delivery"]


def test_custom_sweep_respected(domain_populated_db: str):
    rows = volume_sensitivity(
        domain_populated_db, deliveries_per_day_points=[100, 200, 400, 800]
    )
    assert sorted({r["deliveries_per_day"] for r in rows}) == [100, 200, 400, 800]


def test_domain_filter_restricts_output(domain_populated_db: str):
    rows = volume_sensitivity(
        domain_populated_db, delivery_domains=["food_delivery"]
    )
    assert {r["delivery_domain"] for r in rows} == {"food_delivery"}


def test_metadata_surfaces_capacity_model_info():
    md = sensitivity_metadata("dense_urban_capacity")
    assert md["capacity_model_name"] == "dense_urban_capacity"
    assert md["deliveries_per_drone_per_day"] == 30.0
    assert md["sweep_points"] == DEFAULT_DELIVERIES_PER_DAY_SWEEP


def test_three_capacity_profiles_registered():
    assert set(list_capacity_models()) == {
        "pilot_capacity", "regional_capacity", "dense_urban_capacity",
    }


# ── Immutability: read-only invariant ───────────────────────────────────────

def _table_digest(db: str, table: str) -> str:
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
        h = hashlib.sha256()
        for row in cur:
            h.update(repr(row).encode("utf-8"))
    finally:
        conn.close()
    return h.hexdigest()


def test_sensitivity_does_not_mutate_any_table(domain_populated_db: str):
    db = domain_populated_db
    tables = (
        "delivery_events", "telemetry_observations", "trips",
        "trip_economics_snapshots", "trip_scale_snapshots",
        "transformation_runs", "drones", "orders",
    )
    before = {t: _table_digest(db, t) for t in tables}
    volume_sensitivity(db)
    volume_sensitivity(db, capacity_model="dense_urban_capacity")
    volume_sensitivity(db, deliveries_per_day_points=[10, 20, 30])
    legacy_fixed_overhead_sensitivity(db)
    after = {t: _table_digest(db, t) for t in tables}
    for t in tables:
        assert before[t] == after[t], f"{t} digest changed — sensitivity wrote to it"


# ═════════════════════════════════════════════════════════════════════════════
# Legacy (Phase 27) — still works as before
# ═════════════════════════════════════════════════════════════════════════════

def test_legacy_sensitivity_still_returns_phase27_shape(domain_populated_db: str):
    """The legacy formula must keep emitting the Phase 27 row shape so
    the Phase 27 chart artifact still renders.  No new keys, no removed
    keys."""
    rows = legacy_fixed_overhead_sensitivity(domain_populated_db)
    assert rows
    expected = {
        "delivery_domain", "scale_model", "deliveries_per_day",
        "avg_operational_cost", "avg_amortized_overhead",
        "avg_effective_profit", "break_even_rate", "trip_count",
    }
    for r in rows:
        missing = expected - set(r.keys())
        assert not missing, f"legacy row missing: {missing}"


def test_legacy_overhead_strictly_decreases_with_volume(domain_populated_db: str):
    """The fixed-overhead formula's defining property — kept as a
    regression guard against accidentally modifying the legacy path."""
    rows = legacy_fixed_overhead_sensitivity(domain_populated_db)
    by_domain: dict[str, list[tuple[int, float]]] = {}
    for r in rows:
        by_domain.setdefault(r["delivery_domain"], []).append(
            (r["deliveries_per_day"], r["avg_amortized_overhead"])
        )
    for series in by_domain.values():
        series.sort()
        for (d_low, oh_low), (d_high, oh_high) in zip(series, series[1:]):
            assert oh_high < oh_low


def test_legacy_metadata_helper_works():
    md = legacy_sensitivity_metadata("pilot_program")
    assert md["scale_model_name"] == "pilot_program"
    assert md["sweep_points"] == DEFAULT_DELIVERIES_PER_DAY_SWEEP


# ═════════════════════════════════════════════════════════════════════════════
# Phase 29: domain volume response
# ═════════════════════════════════════════════════════════════════════════════

# ── Pure-helper bounds (no DB) ──────────────────────────────────────────────

def test_efficiency_credit_is_zero_at_zero_volume():
    dom = get_domain("food_delivery")
    assert domain_efficiency_credit(
        deliveries_per_day=0, avg_operational_cost=10.0, domain=dom
    ) == 0.0


def test_efficiency_credit_caps_at_op_cost_times_rate():
    """Concrete upper bound, not 'is bounded across the sweep'."""
    dom = get_domain("food_delivery")
    cap = 10.0 * dom.volume_efficiency_gain_rate
    # Far above saturation — credit must equal the cap (within float noise).
    credit = domain_efficiency_credit(
        deliveries_per_day=1_000_000,
        avg_operational_cost=10.0,
        domain=dom,
    )
    assert credit == pytest.approx(cap)


def test_efficiency_credit_monotonically_non_decreasing():
    dom = get_domain("food_delivery")
    prev = -1.0
    for d in (10, 50, 200, 1000, 4000, 10000):
        cur = domain_efficiency_credit(
            deliveries_per_day=d, avg_operational_cost=10.0, domain=dom,
        )
        assert cur >= prev, f"efficiency credit decreased at d={d}"
        prev = cur


def test_value_decay_is_zero_at_zero_volume():
    dom = get_domain("food_delivery")
    assert domain_value_decay(
        deliveries_per_day=0, avg_revenue=25.0, domain=dom
    ) == 0.0


def test_value_decay_caps_at_revenue_times_rate():
    dom = get_domain("food_delivery")
    cap = 25.0 * dom.volume_value_decay_rate
    decay = domain_value_decay(
        deliveries_per_day=1_000_000, avg_revenue=25.0, domain=dom,
    )
    assert decay == pytest.approx(cap)


def test_value_decay_monotonically_non_decreasing():
    dom = get_domain("food_delivery")
    prev = -1.0
    for d in (10, 50, 200, 1000, 4000, 10000):
        cur = domain_value_decay(
            deliveries_per_day=d, avg_revenue=25.0, domain=dom,
        )
        assert cur >= prev
        prev = cur


def test_both_terms_saturate_at_saturation_volume_per_day():
    """At exactly saturation_volume_per_day, both terms hit their cap."""
    dom = get_domain("food_delivery")
    d_sat = dom.saturation_volume_per_day
    credit_at_sat = domain_efficiency_credit(
        deliveries_per_day=d_sat, avg_operational_cost=10.0, domain=dom,
    )
    decay_at_sat  = domain_value_decay(
        deliveries_per_day=d_sat, avg_revenue=25.0, domain=dom,
    )
    assert credit_at_sat == pytest.approx(10.0 * dom.volume_efficiency_gain_rate)
    assert decay_at_sat  == pytest.approx(25.0 * dom.volume_value_decay_rate)


# ── End-to-end response in the sensitivity output ───────────────────────────

def test_response_fields_per_row_are_bounded(domain_populated_db: str):
    """Walk every row and confirm credit/decay never exceed their per-row
    upper bounds.  Row values are stored as ``round(., 4)`` so we allow
    a rounding-scale slack of 5e-5 on the upper bound."""
    rows = volume_sensitivity(domain_populated_db)
    for r in rows:
        dom = get_domain(r["delivery_domain"])
        credit_cap = r["avg_operational_cost"] * dom.volume_efficiency_gain_rate
        decay_cap  = r["avg_revenue"]          * dom.volume_value_decay_rate
        assert 0.0 <= r["domain_efficiency_credit"] <= credit_cap + 5e-5, (
            f"{r['delivery_domain']} d={r['deliveries_per_day']}: "
            f"credit {r['domain_efficiency_credit']} > cap {credit_cap}"
        )
        assert 0.0 <= r["domain_value_decay"] <= decay_cap + 5e-5, (
            f"{r['delivery_domain']} d={r['deliveries_per_day']}: "
            f"decay {r['domain_value_decay']} > cap {decay_cap}"
        )


def test_adjusted_decomposition_matches_effective_profit(domain_populated_db: str):
    """The audit-trail invariant: avg_effective_profit must equal
    (adjusted_revenue − adjusted_op_cost − capacity_overhead) within
    rounding tolerance.  If this ever fails, the row's columns are
    no longer self-consistent."""
    for r in volume_sensitivity(domain_populated_db):
        recomputed = (
            r["adjusted_avg_revenue"]
            - r["adjusted_avg_operational_cost"]
            - r["capacity_overhead_per_delivery"]
        )
        assert r["avg_effective_profit"] == pytest.approx(recomputed, abs=1e-2)


def test_curves_differ_in_shape_not_just_offset(domain_populated_db: str):
    """The whole point of Phase 29: domain curves must differ by more
    than a constant vertical shift.

    Concretely: compute the *change* in avg_effective_profit from the
    smallest to the largest sweep point for each domain.  At least two
    domains' deltas must differ by ≥ $1.
    """
    rows = volume_sensitivity(domain_populated_db)
    d_lo = min(r["deliveries_per_day"] for r in rows)
    d_hi = max(r["deliveries_per_day"] for r in rows)
    deltas: dict[str, float] = {}
    for r in rows:
        if r["deliveries_per_day"] not in (d_lo, d_hi): continue
        prev = deltas.get(r["delivery_domain"], 0.0)
        # Subtract low, add high — equivalent to delta = high − low.
        if r["deliveries_per_day"] == d_lo:
            deltas[r["delivery_domain"]] = prev - r["avg_effective_profit"]
        else:
            deltas[r["delivery_domain"]] = prev + r["avg_effective_profit"]
    vals = sorted(deltas.values())
    spread = vals[-1] - vals[0]
    assert spread >= 1.0, (
        f"curve shape barely differs across domains — delta spread = ${spread:.2f}; "
        f"per-domain deltas = {deltas}"
    )


def test_changing_efficiency_gain_rate_changes_curve_shape(domain_populated_db: str):
    """Sanity: doubling the efficiency_gain_rate on one domain must
    visibly move its effective-profit curve.  Uses a synthetic in-memory
    DeliveryDomain so we don't mutate the registry.
    """
    # Inject a synthetic domain by name override — same trick the matrix
    # tests use.  Pull the base food_delivery, double its rate.
    base    = get_domain("food_delivery")
    boosted = replace(base, name="_test_boost", volume_efficiency_gain_rate=base.volume_efficiency_gain_rate * 3)
    # No straightforward way to inject a DeliveryDomain via the
    # snapshot table, so we exercise the helpers directly instead.
    d = 1000
    base_credit    = domain_efficiency_credit(
        deliveries_per_day=d, avg_operational_cost=10.0, domain=base,
    )
    boosted_credit = domain_efficiency_credit(
        deliveries_per_day=d, avg_operational_cost=10.0, domain=boosted,
    )
    assert boosted_credit > base_credit
    assert boosted_credit == pytest.approx(base_credit * 3)


def test_changing_value_decay_rate_changes_curve_shape(domain_populated_db: str):
    base    = get_domain("food_delivery")
    boosted = replace(base, name="_test_decay", volume_value_decay_rate=base.volume_value_decay_rate * 2)
    d = 2000
    base_decay    = domain_value_decay(
        deliveries_per_day=d, avg_revenue=25.0, domain=base,
    )
    boosted_decay = domain_value_decay(
        deliveries_per_day=d, avg_revenue=25.0, domain=boosted,
    )
    assert boosted_decay > base_decay
    assert boosted_decay == pytest.approx(base_decay * 2)


def test_response_magnitude_visible_but_not_dominant(domain_populated_db: str):
    """Response effects should be on the order of cents-to-dollars per
    delivery — visible but not dominant relative to capacity overhead.

    Concretely: for at least one domain at d=1000 (moderate volume),
    the net domain response magnitude must be > $0.10 (visible) AND
    < capacity_overhead_per_delivery (not dominant).
    """
    rows = volume_sensitivity(domain_populated_db)
    moderate = [r for r in rows if r["deliveries_per_day"] == 1000]
    assert moderate, "no d=1000 rows"
    visible = any(abs(r["net_domain_response"]) > 0.10 for r in moderate)
    dominant = any(
        abs(r["net_domain_response"]) >= r["capacity_overhead_per_delivery"]
        for r in moderate
    )
    assert visible,  "response is too small to be visible at d=1000"
    assert not dominant, "response dominates capacity overhead at d=1000"


def test_registry_version_at_v3():
    """v3 = Phase 29 revision (retail saturation retune + addressable-
    demand framing).  Keep this explicit so any future bump is
    deliberate."""
    from core.delivery_domains import DELIVERY_DOMAIN_REGISTRY_VERSION
    assert DELIVERY_DOMAIN_REGISTRY_VERSION == "v3"


# ── Phase 29 revision: addressable-demand flag ──────────────────────────────

def test_within_addressable_demand_matches_saturation_threshold(domain_populated_db: str):
    """For every row, ``within_addressable_demand`` must be True iff
    deliveries_per_day ≤ that domain's saturation_volume_per_day."""
    for r in volume_sensitivity(domain_populated_db):
        dom = get_domain(r["delivery_domain"])
        expected = r["deliveries_per_day"] <= dom.saturation_volume_per_day
        assert r["within_addressable_demand"] is expected, (
            f"{r['delivery_domain']} d={r['deliveries_per_day']} "
            f"sat={dom.saturation_volume_per_day}: flag={r['within_addressable_demand']}"
        )


def test_default_sweep_exercises_both_addressable_states(domain_populated_db: str):
    """The default sweep must produce some rows within addressable demand
    AND some rows beyond — otherwise the clip behavior is never
    exercised by the chart pipeline."""
    rows = volume_sensitivity(domain_populated_db)
    within = sum(1 for r in rows if r["within_addressable_demand"])
    beyond = sum(1 for r in rows if not r["within_addressable_demand"])
    assert within > 0, "no rows within addressable demand — sweep too sparse at low end"
    assert beyond > 0, (
        "no rows beyond addressable demand — sweep does not exceed any "
        "domain's saturation, so the clip / dashed-extension is never "
        "exercised.  Either densify the sweep or lower a saturation."
    )


def test_retail_package_saturation_dropped_to_3000():
    """Phase 29 revision: retail_package's addressable ceiling moved
    from 5000 to 3000.  Guard against accidental re-bump."""
    assert get_domain("retail_package").saturation_volume_per_day == 3000


# ── Phase 29 rev: viability summary ─────────────────────────────────────────

def test_viability_summary_covers_all_cells(domain_populated_db: str):
    from core.volume_sensitivity import compute_viability_summary
    from core.capacity_models   import list_capacity_models
    cells = compute_viability_summary(domain_populated_db)
    expected_cells = len(list_capacity_models()) * 2  # food + retail are
                                                       # populated by the
                                                       # domain_populated_db
                                                       # fixture (retail by
                                                       # default, food by
                                                       # explicit recompute)
    assert len(cells) == expected_cells, (
        f"expected {expected_cells} cells ({len(list_capacity_models())} "
        f"capacities × 2 domains), got {len(cells)}"
    )


def test_viability_summary_row_shape(domain_populated_db: str):
    from core.volume_sensitivity import compute_viability_summary
    expected = {
        "capacity_model", "delivery_domain", "addressable_ceiling",
        "breakeven_deliveries_per_day", "viable_within_addressable_demand",
    }
    for c in compute_viability_summary(domain_populated_db):
        missing = expected - set(c.keys())
        assert not missing, f"missing: {missing}"


def test_viability_state_helper():
    from core.volume_sensitivity import viability_state
    assert viability_state({
        "breakeven_deliveries_per_day": 250, "addressable_ceiling": 4000,
    }) == "viable"
    assert viability_state({
        "breakeven_deliveries_per_day": 2500, "addressable_ceiling": 600,
    }) == "beyond"
    assert viability_state({
        "breakeven_deliveries_per_day": None, "addressable_ceiling": 800,
    }) == "never"


def test_viability_summary_respects_addressable_ceiling(domain_populated_db: str):
    """If a cell's breakeven sits within the ceiling, the viable flag is
    True; otherwise False.  Math sanity check across every cell."""
    from core.volume_sensitivity import compute_viability_summary
    for c in compute_viability_summary(domain_populated_db):
        be = c["breakeven_deliveries_per_day"]
        if be is None:
            assert c["viable_within_addressable_demand"] is False
        else:
            assert c["viable_within_addressable_demand"] == (
                be <= c["addressable_ceiling"]
            )


def test_viability_summary_capacity_model_filter(domain_populated_db: str):
    from core.volume_sensitivity import compute_viability_summary
    cells = compute_viability_summary(
        domain_populated_db, capacity_models=["dense_urban_capacity"],
    )
    assert cells
    assert {c["capacity_model"] for c in cells} == {"dense_urban_capacity"}
