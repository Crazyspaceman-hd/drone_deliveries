"""Phase 30: portfolio_summary aggregator round-trip + JSON-shape tests."""

from __future__ import annotations

import json

import pytest

from transforms import economics
from core.portfolio_summary import generate_portfolio_summary


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
        "headline", "validation", "run_counts", "charts_dir",
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
