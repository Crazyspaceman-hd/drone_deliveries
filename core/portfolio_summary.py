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
from core.volume_sensitivity import compute_viability_summary, viability_state


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
        "validation":                      validation_compact,
        "run_counts":                      _run_counts(db_path),
        "charts_dir":                      CHARTS_DIR_DEFAULT,
    }
