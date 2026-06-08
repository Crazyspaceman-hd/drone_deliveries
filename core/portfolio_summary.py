"""
core/portfolio_summary.py

One-shot aggregator for portfolio-facing presentation surfaces.

The README, the workbench Overview, the recruiter doc — they all want
the same set of derived facts from the analytical layer.  Rather than
each surface reaching into ``core/volume_sensitivity``, ``core/runs``,
``core/validation`` etc. and re-deriving the same headlines, this module
exposes a single :func:`generate_portfolio_summary` that bundles
everything.

Design rules
─────────────
* **Registry-driven.** No hard-coded capacity-model or domain names.
  Anything that summarises across capacities iterates the current
  registry.  Adding a fourth capacity profile in the future surfaces
  automatically in every downstream surface that consumes this dict.
* **No new analytics.** Every key is a thin re-projection of an
  existing ``compute_*`` / ``list_*`` / ``generate_*`` function.  If
  this module ever grows new business logic, that logic belongs in the
  appropriate domain module instead.
* **JSON-serialisable.** ``json.dumps(generate_portfolio_summary(db))``
  must succeed without a custom encoder — so the README + docs can
  embed the live dump in a ``<details>`` block for auditability.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from core.capacity_models    import list_capacity_models
from core.delivery_domains   import list_domains
from core.validation         import generate_validation_summary
from core.volume_sensitivity import (
    compute_viability_summary, viability_state, volume_sensitivity,
)


CHARTS_DIR_DEFAULT = "outputs/charts"


def _run_counts(db_path: str) -> dict:
    """How many simulation_runs / experiment_runs rows in the DB."""
    out = {"simulation_runs": 0, "experiments": 0}
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.OperationalError:
        return out
    try:
        for table, key in (
            ("simulation_runs", "simulation_runs"),
            ("experiment_runs", "experiments"),
        ):
            try:
                out[key] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                # Table may not exist on very old DBs (pre-Phase-15 / 24).
                out[key] = 0
    finally:
        conn.close()
    return out


def _viability_breakdown(cells: list[dict]) -> dict:
    """Aggregate viability counts across cells, per capacity model and
    in total.  Returns a registry-friendly structure so a new capacity
    model surfaces without touching the README template."""
    total = {"viable": 0, "beyond": 0, "never": 0}
    by_cap: dict[str, dict[str, int]] = {}
    for c in cells:
        state = viability_state(c)
        total[state] = total.get(state, 0) + 1
        cap = c["capacity_model"]
        bucket = by_cap.setdefault(cap, {"viable": 0, "beyond": 0, "never": 0})
        bucket[state] = bucket.get(state, 0) + 1

    fully_viable: list[str] = []
    fully_red:    list[str] = []
    mixed:        list[str] = []
    for cap, counts in by_cap.items():
        non_zero = {s for s, n in counts.items() if n > 0}
        if non_zero == {"viable"}:
            fully_viable.append(cap)
        elif non_zero == {"never"}:
            fully_red.append(cap)
        else:
            mixed.append(cap)

    return {
        "totals":                          total,
        "by_capacity":                     by_cap,
        "capacity_models_fully_viable":    sorted(fully_viable),
        "capacity_models_fully_red":       sorted(fully_red),
        "capacity_models_mixed":           sorted(mixed),
    }


def _headline(cells: list[dict]) -> dict:
    """A handful of derived facts that the README and docs reference
    by name.  Kept narrow on purpose — anything more elaborate belongs
    on its own dedicated surface."""
    # Lowest breakeven across viable cells.  Ties → list of all winners.
    viable_cells = [c for c in cells if c["viable_within_addressable_demand"]]
    lowest: list[dict] = []
    if viable_cells:
        min_be = min(c["breakeven_deliveries_per_day"] for c in viable_cells)
        lowest = sorted(
            [
                {
                    "capacity_model":             c["capacity_model"],
                    "delivery_domain":            c["delivery_domain"],
                    "breakeven_deliveries_per_day": c["breakeven_deliveries_per_day"],
                    "addressable_ceiling":        c["addressable_ceiling"],
                }
                for c in viable_cells
                if c["breakeven_deliveries_per_day"] == min_be
            ],
            key=lambda c: (c["capacity_model"], c["delivery_domain"]),
        )

    # Tightest addressable ceiling across all domains.
    tightest = None
    if cells:
        # All cells for a domain share the same ceiling; one per domain
        # is fine.
        seen: dict[str, int] = {}
        for c in cells:
            seen.setdefault(c["delivery_domain"], c["addressable_ceiling"])
        dom_min = min(seen, key=lambda d: seen[d])
        tightest = {"domain": dom_min, "ceiling": int(seen[dom_min])}

    return {
        "lowest_breakeven_cells":       lowest,
        "tightest_addressable_ceiling": tightest,
    }


# ── Pain points: WHY each non-viable cell fails ─────────────────────────────
#
# The viability grid says *what* fails.  Diagnostics name *why*.  No new
# analytics — just a per-cell reading of the existing volume-sensitivity
# output anchored at the largest sweep point that's still within the
# domain's addressable demand.  This is the deepest the model is allowed
# to look at the cell honestly; anything past the ceiling is
# extrapolation.

def diagnose_viability_cells(
    db_path: str,
    *,
    deliveries_per_day_points: Optional[list[int]] = None,
) -> list[dict]:
    """Per-cell failure attribution.

    For every (capacity_model × delivery_domain) cell, anchor the
    diagnosis at the largest sweep point that's still within the
    domain's addressable demand.  At that anchor, the row's numbers
    answer the question *"under the most favorable addressable
    conditions, why is this cell where it is?"*

    Returns:
        list of records (sorted by capacity_model, delivery_domain)::

            capacity_model
            delivery_domain
            state                          viable / beyond / never
            dominant_constraint            viable / capacity_overhead /
                                           addressable_demand / mixed
            addressable_ceiling
            breakeven_deliveries_per_day   (or None)
            anchor_deliveries_per_day      (largest d ≤ ceiling)
            anchor_required_drones
            anchor_overhead_per_delivery
            anchor_profit_before_overhead  (= adj_revenue − adj_op_cost)
            anchor_effective_profit        (= profit_before_overhead −
                                            overhead; signed)
            gap_at_anchor                  alias of anchor_effective_profit

    No writes; pure read-only diagnostic.
    """
    cells = compute_viability_summary(
        db_path, deliveries_per_day_points=deliveries_per_day_points,
    )

    # Pull volume_sensitivity once per capacity model and slice locally.
    sensitivity: dict[str, list[dict]] = {}
    for cap in {c["capacity_model"] for c in cells}:
        sensitivity[cap] = volume_sensitivity(
            db_path,
            capacity_model            = cap,
            deliveries_per_day_points = deliveries_per_day_points,
        )

    diagnostics: list[dict] = []
    for cell in cells:
        cap = cell["capacity_model"]
        dom = cell["delivery_domain"]
        ceiling = int(cell["addressable_ceiling"])
        state = viability_state(cell)

        within_rows = [
            r for r in sensitivity[cap]
            if r["delivery_domain"] == dom and r["within_addressable_demand"]
        ]
        if not within_rows:
            # Sweep doesn't reach this domain at all — shouldn't happen
            # with the default sweep but defensible.
            diagnostics.append({
                "capacity_model":                cap,
                "delivery_domain":               dom,
                "state":                          state,
                "dominant_constraint":            "no_data",
                "addressable_ceiling":            ceiling,
                "breakeven_deliveries_per_day":   cell["breakeven_deliveries_per_day"],
                "anchor_deliveries_per_day":      None,
                "anchor_required_drones":         None,
                "anchor_overhead_per_delivery":   None,
                "anchor_profit_before_overhead":  None,
                "anchor_effective_profit":        None,
                "gap_at_anchor":                  None,
            })
            continue

        anchor = max(within_rows, key=lambda r: r["deliveries_per_day"])
        # profit_before_overhead = adjusted_revenue − adjusted_op_cost
        profit_before_overhead = round(
            anchor["adjusted_avg_revenue"]
            - anchor["adjusted_avg_operational_cost"],
            2,
        )
        overhead   = round(anchor["capacity_overhead_per_delivery"], 2)
        effective  = round(anchor["avg_effective_profit"], 2)

        # Attribute the dominant constraint.
        if state == "viable":
            dominant = "viable"
        elif state == "beyond":
            # Break-even exists, just past the ceiling.  Demand is the
            # binding constraint by definition.
            dominant = "addressable_demand"
        else:  # never
            # Even at the best within-addressable point, overhead
            # exceeds source value.  Capacity overhead is the dominant
            # binding constraint.
            if overhead > profit_before_overhead:
                dominant = "capacity_overhead"
            else:
                # Defensive — `never` should imply overhead > profit
                # somewhere, but if the sweep is sparse we fall back to
                # `mixed`.
                dominant = "mixed"

        diagnostics.append({
            "capacity_model":                cap,
            "delivery_domain":               dom,
            "state":                          state,
            "dominant_constraint":            dominant,
            "addressable_ceiling":            ceiling,
            "breakeven_deliveries_per_day":   cell["breakeven_deliveries_per_day"],
            "anchor_deliveries_per_day":      int(anchor["deliveries_per_day"]),
            "anchor_required_drones":         int(anchor["required_drones"]),
            "anchor_overhead_per_delivery":   overhead,
            "anchor_profit_before_overhead":  profit_before_overhead,
            "anchor_effective_profit":        effective,
            "gap_at_anchor":                  effective,
        })

    diagnostics.sort(key=lambda d: (d["capacity_model"], d["delivery_domain"]))
    return diagnostics


def aggregate_pain_points(diagnostics: list[dict]) -> dict:
    """Plain-English observations the README + frontend render verbatim.

    No new logic — just groups diagnostics by capacity model and
    dominant constraint, surfaces aggregate patterns, and returns a
    bundle that downstream surfaces consume directly.
    """
    # Counts by dominant constraint across all cells.
    constraint_counts: dict[str, int] = {}
    for d in diagnostics:
        constraint_counts[d["dominant_constraint"]] = \
            constraint_counts.get(d["dominant_constraint"], 0) + 1

    # Group by capacity model so we can detect "uniformly red / viable".
    by_cap: dict[str, list[dict]] = {}
    for d in diagnostics:
        by_cap.setdefault(d["capacity_model"], []).append(d)

    observations: list[dict] = []
    for cap, cells in sorted(by_cap.items()):
        states = {c["state"] for c in cells}
        if states == {"never"}:
            # All red.  Surface the worst (most negative) gap so the
            # observation carries a concrete number.
            gaps = [c["gap_at_anchor"] for c in cells
                    if c.get("gap_at_anchor") is not None]
            worst = min(gaps) if gaps else None
            observations.append({
                "kind":                    "capacity_uniformly_red",
                "capacity_model":          cap,
                "headline":                (
                    f"{cap} is uniformly red — every domain hits a "
                    f"capacity-overhead floor that exceeds source profit at "
                    f"maximum addressable demand."
                ),
                "worst_gap_per_delivery":  worst,
                "cells":                   [c["delivery_domain"] for c in cells],
            })
        elif states == {"viable"}:
            # All green.  Surface the lowest breakeven.
            bes = [c["breakeven_deliveries_per_day"] for c in cells
                   if c.get("breakeven_deliveries_per_day") is not None]
            min_be = min(bes) if bes else None
            observations.append({
                "kind":                    "capacity_uniformly_viable",
                "capacity_model":          cap,
                "headline":                (
                    f"{cap} achieves break-even for every domain within "
                    f"addressable demand; lowest at "
                    f"{min_be} deliveries/day."
                ),
                "lowest_breakeven":        min_be,
                "cells":                   [c["delivery_domain"] for c in cells],
            })
        elif "beyond" in states and "viable" not in states:
            observations.append({
                "kind":                    "capacity_addressable_capped",
                "capacity_model":          cap,
                "headline":                (
                    f"{cap} can clear break-even on paper for some domains, "
                    f"but only past the addressable-demand ceiling — the "
                    f"binding constraint is volume, not cost."
                ),
                "cells":                   [c["delivery_domain"] for c in cells],
            })
        else:
            observations.append({
                "kind":                    "capacity_mixed",
                "capacity_model":          cap,
                "headline":                (
                    f"{cap} is mixed across the four domains — viability "
                    f"depends on which demand profile you serve."
                ),
                "cells":                   [c["delivery_domain"] for c in cells],
            })

    return {
        "diagnostics":       diagnostics,
        "constraint_counts": constraint_counts,
        "observations":      observations,
    }


def generate_portfolio_summary(db_path: str) -> dict:
    """The one dict the README, Overview page, and recruiter doc all
    consume.  Registry-driven so new capacity / domain entries surface
    automatically.

    Returns:
        dict with the following keys::

            viability               list of compute_viability_summary cells
            viability_states        {viable, beyond, never} totals
            viability_by_capacity   {capacity_model -> state counts}
            capacity_models_fully_viable   list[str]
            capacity_models_fully_red      list[str]
            capacity_models_mixed          list[str]
            capacity_models         registry list
            delivery_domains        registry list
            headline                derived facts (lowest break-even,
                                    tightest addressable ceiling)
            validation              generate_validation_summary output
            run_counts              {simulation_runs, experiments}
            charts_dir              relative path of the charts output

    Every value is JSON-serialisable without a custom encoder.
    """
    cells       = compute_viability_summary(db_path)
    # Attach the categorical state to each cell so the README's JSON
    # dump matches what the API returns (which also includes ``state``).
    for c in cells:
        c["state"] = viability_state(c)

    breakdown   = _viability_breakdown(cells)
    headline    = _headline(cells)
    diagnostics = diagnose_viability_cells(db_path)
    pain_points = aggregate_pain_points(diagnostics)
    validation  = generate_validation_summary(db_path)
    # Strip the per-rule ``results`` list from the embedded validation
    # block — it's a large array that bloats the JSON dump without
    # adding portfolio signal.  Counts + any_errors are what the
    # README needs.
    validation_compact = {
        k: v for k, v in validation.items() if k != "results"
    }

    return {
        "viability":                       cells,
        "viability_states":                breakdown["totals"],
        "viability_by_capacity":           breakdown["by_capacity"],
        "capacity_models_fully_viable":    breakdown["capacity_models_fully_viable"],
        "capacity_models_fully_red":       breakdown["capacity_models_fully_red"],
        "capacity_models_mixed":           breakdown["capacity_models_mixed"],
        "capacity_models":                 list_capacity_models(),
        "delivery_domains":                list_domains(),
        "headline":                        headline,
        "pain_points":                     pain_points,
        "validation":                      validation_compact,
        "run_counts":                      _run_counts(db_path),
        "charts_dir":                      CHARTS_DIR_DEFAULT,
    }
