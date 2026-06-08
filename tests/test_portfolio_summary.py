"""Phase 30: portfolio_summary aggregator round-trip + JSON-shape tests."""

from __future__ import annotations

import json

import pytest

from transforms import economics
from core.portfolio_summary import (
    aggregate_pain_points, diagnose_viability_cells,
    generate_portfolio_summary,
)


@pytest.fixture
def populated_db(writable_db) -> str:
    """A DB with at least two domains populated so viability cells are
    non-empty for every capacity_model."""
    db, _rid = writable_db
    economics.run(db, delivery_domain="food_delivery")
    return db


# ─────────────────────────────────────────────────────────────────────────────
# Shape
# ─────────────────────────────────────────────────────────────────────────────

def test_summary_emits_every_documented_key(populated_db: str):
    expected = {
        "viability", "viability_states", "viability_by_capacity",
        "capacity_models_fully_viable", "capacity_models_fully_red",
        "capacity_models_mixed",
        "capacity_models", "delivery_domains",
        "headline", "pain_points",
        "validation", "run_counts", "charts_dir",
    }
    s = generate_portfolio_summary(populated_db)
    missing = expected - set(s.keys())
    assert not missing, f"missing keys: {missing}"


def test_summary_is_json_serialisable_without_custom_encoder(populated_db: str):
    """No ``default=str`` allowed.  Anything in the dict must be a
    native JSON type — anything else means the README's live snapshot
    can't be embedded cleanly."""
    s = generate_portfolio_summary(populated_db)
    json.dumps(s)  # raises if anything is non-serialisable


def test_viability_breakdown_partitions_capacity_models(populated_db: str):
    """Each registered capacity model must land in exactly one of
    fully_viable / fully_red / mixed."""
    s = generate_portfolio_summary(populated_db)
    caps = set(s["capacity_models"])
    a = set(s["capacity_models_fully_viable"])
    b = set(s["capacity_models_fully_red"])
    c = set(s["capacity_models_mixed"])
    # All three lists are subsets of the registry…
    for bucket in (a, b, c):
        assert bucket <= caps, f"unknown capacity in bucket: {bucket - caps}"
    # …and they partition cleanly (no overlaps).
    assert not (a & b)
    assert not (a & c)
    assert not (b & c)
    # Their union equals the set of capacities that actually had cells
    # computed.  A capacity with no viability cells (e.g. no snapshots
    # at all for any domain it covers) wouldn't appear in any bucket;
    # that's correct behaviour.
    capacities_with_cells = {c["capacity_model"] for c in s["viability"]}
    assert a | b | c == capacities_with_cells


def test_viability_totals_match_per_capacity_sums(populated_db: str):
    s = generate_portfolio_summary(populated_db)
    summed = {"viable": 0, "beyond": 0, "never": 0}
    for counts in s["viability_by_capacity"].values():
        for k, n in counts.items():
            summed[k] += n
    assert summed == s["viability_states"]


def test_headline_lowest_breakeven_is_a_list(populated_db: str):
    """Tie handling: lowest_breakeven_cells is always a list (possibly
    empty if no cell is viable).  Each entry has the four documented
    keys."""
    s = generate_portfolio_summary(populated_db)
    lowest = s["headline"]["lowest_breakeven_cells"]
    assert isinstance(lowest, list)
    for cell in lowest:
        for k in ("capacity_model", "delivery_domain",
                  "breakeven_deliveries_per_day", "addressable_ceiling"):
            assert k in cell


def test_headline_tightest_ceiling_picks_smallest_domain_ceiling(populated_db: str):
    """The tightest ceiling is the smallest saturation_volume_per_day
    across the populated domains.  ``urgent_documents`` has 600/day in
    the built-in registry, which is the smallest; ``medical_delivery``
    is next at 800."""
    s = generate_portfolio_summary(populated_db)
    tight = s["headline"]["tightest_addressable_ceiling"]
    if tight is None:
        return  # no cells — nothing to assert.
    # The smallest ceiling across populated domains.
    smallest = min(c["addressable_ceiling"] for c in s["viability"])
    assert tight["ceiling"] == smallest


def test_validation_block_present_and_compact(populated_db: str):
    """The aggregator strips the long per-rule ``results`` array from
    the validation block — leaving only counts + the any_errors flag —
    so the JSON dump stays embeddable."""
    s = generate_portfolio_summary(populated_db)
    v = s["validation"]
    assert "results" not in v, "results array should be stripped"
    for k in ("counts_by_severity", "failed_by_severity", "any_errors"):
        assert k in v


def test_run_counts_present(populated_db: str):
    s = generate_portfolio_summary(populated_db)
    rc = s["run_counts"]
    assert "simulation_runs" in rc
    assert "experiments"     in rc
    assert rc["simulation_runs"] >= 1   # writable_db seeds one run


# ─────────────────────────────────────────────────────────────────────────────
# Pain-points diagnostics
# ─────────────────────────────────────────────────────────────────────────────

def test_diagnostics_emit_required_keys(populated_db: str):
    expected = {
        "capacity_model", "delivery_domain", "state",
        "dominant_constraint", "addressable_ceiling",
        "breakeven_deliveries_per_day",
        "anchor_deliveries_per_day", "anchor_required_drones",
        "anchor_overhead_per_delivery", "anchor_profit_before_overhead",
        "anchor_effective_profit", "gap_at_anchor",
    }
    diagnostics = diagnose_viability_cells(populated_db)
    assert diagnostics, "no diagnostics produced"
    for d in diagnostics:
        missing = expected - set(d.keys())
        assert not missing, f"missing keys: {missing}"


def test_dominant_constraint_is_one_of_documented_values(populated_db: str):
    valid = {"viable", "capacity_overhead", "addressable_demand",
             "mixed", "no_data"}
    for d in diagnose_viability_cells(populated_db):
        assert d["dominant_constraint"] in valid, (
            f"unexpected dominant_constraint: {d['dominant_constraint']}"
        )


def test_viable_cells_have_viable_constraint(populated_db: str):
    """A `viable` state must carry dominant_constraint='viable' — never
    a failure attribution.  Otherwise the README will write 'this works
    BECAUSE capacity overhead is too high', which is nonsense."""
    for d in diagnose_viability_cells(populated_db):
        if d["state"] == "viable":
            assert d["dominant_constraint"] == "viable"


def test_never_cells_have_negative_gap_at_anchor(populated_db: str):
    """A `never` cell means *no* sweep point cleared zero — so at the
    anchor (largest within-addressable sweep), effective profit must
    be ≤ 0.  Math sanity check."""
    for d in diagnose_viability_cells(populated_db):
        if d["state"] == "never" and d["gap_at_anchor"] is not None:
            assert d["gap_at_anchor"] <= 0


def test_aggregate_observation_kinds_are_well_defined():
    """Aggregate observation kinds must be drawn from a fixed set so
    the frontend's plain-English templates don't have to handle
    surprises."""
    valid_kinds = {
        "capacity_uniformly_red",
        "capacity_uniformly_viable",
        "capacity_addressable_capped",
        "capacity_mixed",
    }
    # Build synthetic diagnostics covering each pattern.
    samples = [
        # uniformly red
        {"capacity_model": "x", "delivery_domain": "a", "state": "never",
         "dominant_constraint": "capacity_overhead",
         "breakeven_deliveries_per_day": None, "gap_at_anchor": -10.0},
        {"capacity_model": "x", "delivery_domain": "b", "state": "never",
         "dominant_constraint": "capacity_overhead",
         "breakeven_deliveries_per_day": None, "gap_at_anchor": -8.0},
        # uniformly viable
        {"capacity_model": "y", "delivery_domain": "a", "state": "viable",
         "dominant_constraint": "viable",
         "breakeven_deliveries_per_day": 200, "gap_at_anchor": 4.0},
        {"capacity_model": "y", "delivery_domain": "b", "state": "viable",
         "dominant_constraint": "viable",
         "breakeven_deliveries_per_day": 150, "gap_at_anchor": 5.0},
        # uniformly beyond
        {"capacity_model": "z", "delivery_domain": "a", "state": "beyond",
         "dominant_constraint": "addressable_demand",
         "breakeven_deliveries_per_day": 2000, "gap_at_anchor": -1.0},
    ]
    bundle = aggregate_pain_points(samples)
    kinds = {o["kind"] for o in bundle["observations"]}
    assert kinds <= valid_kinds, f"unknown kind(s): {kinds - valid_kinds}"
    assert "capacity_uniformly_red"      in kinds
    assert "capacity_uniformly_viable"   in kinds
    assert "capacity_addressable_capped" in kinds


def test_constraint_counts_sum_to_cell_total(populated_db: str):
    bundle = aggregate_pain_points(diagnose_viability_cells(populated_db))
    n_total = sum(bundle["constraint_counts"].values())
    n_cells = len(bundle["diagnostics"])
    assert n_total == n_cells, (
        f"constraint_counts ({n_total}) != diagnostics ({n_cells})"
    )
