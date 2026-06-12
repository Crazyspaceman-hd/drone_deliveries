"""
core/service_mix_analysis.py

Weighted multi-domain service-mix analysis (Phase 33).

Split-volume model
──────────────────
A service mix at total ``deliveries_per_day = V`` serves component domain
``d`` at ``V × weight_d``.  Each component is read at its own share of
the volume (consistent with Phase 29 addressable-demand ceilings), while
capacity overhead is shared — one fleet sized for the *total* V::

    shared_overhead       = capacity_overhead_per_delivery(capacity, V)
    component_effective(d) = source_profit_d
                           + efficiency_credit(d, V × weight_d)
                           − value_decay(d, V × weight_d)
                           − shared_overhead
    mix_effective          = Σ weight_d × component_effective(d)

The component's *own* capacity overhead (from its V×weight row) is
discarded — the mix shares one fleet, not one fleet per component.

Read-only: reuses ``volume_sensitivity`` against existing economics
snapshots.  No new events, no snapshot mutation.
"""

from __future__ import annotations

from typing import Optional

from core.service_mixes import get_service_mix, list_service_mixes
from core.volume_sensitivity import (
    DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY,
    DEFAULT_DELIVERIES_PER_DAY_SWEEP,
    capacity_overhead_per_delivery,
    volume_sensitivity,
)


def _component_row(
    db_path: str, capacity_model: str, domain: str, component_volume: int,
) -> Optional[dict]:
    """Single volume-sensitivity row for one domain at its component
    volume.  ``None`` if the domain has no economics snapshots."""
    rows = volume_sensitivity(
        db_path,
        capacity_model            = capacity_model,
        delivery_domains          = [domain],
        deliveries_per_day_points = [component_volume],
    )
    return rows[0] if rows else None


def compute_service_mix_summary(
    db_path: str,
    service_mix_names:        Optional[list] = None,
    capacity_model_names:     Optional[list] = None,
    deliveries_per_day_values: Optional[list] = None,
    run_ids:                  Optional[list] = None,   # accepted for API symmetry; unused
) -> list:
    """Per (service_mix × capacity_model × deliveries_per_day) rows.

    See module docstring for the split-volume formula.  Returns ``[]``
    if any component domain lacks economics snapshots for a given cell
    (the whole cell is skipped — a partial blend would be misleading).
    """
    mix_names = service_mix_names or list_service_mixes()
    caps      = capacity_model_names or [DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY]
    volumes   = deliveries_per_day_values or list(DEFAULT_DELIVERIES_PER_DAY_SWEEP)

    out: list = []
    for mix_name in mix_names:
        mix = get_service_mix(mix_name)
        for cap in caps:
            for total_v in volumes:
                total_v = int(total_v)
                shared_overhead = capacity_overhead_per_delivery(cap, total_v)

                comp_details: list = []
                incomplete = False
                # Weighted accumulators.
                w_eff = w_src = w_op = w_rev = w_credit = w_decay = w_be = 0.0
                all_within = True

                for comp in mix.components:
                    cv = max(1, round(total_v * comp.weight))
                    r = _component_row(db_path, cap, comp.delivery_domain, cv)
                    if r is None:
                        incomplete = True
                        break
                    src    = r["avg_source_profit"]
                    op     = r["avg_operational_cost"]
                    rev    = r["avg_revenue"]
                    credit = r["domain_efficiency_credit"]
                    decay  = r["domain_value_decay"]
                    within = r["within_addressable_demand"]
                    all_within = all_within and within
                    # Component effective profit under the SHARED fleet.
                    comp_eff = src + credit - decay - shared_overhead
                    w = comp.weight
                    comp_details.append({
                        "component_domain":            comp.delivery_domain,
                        "mix_weight":                  w,
                        "component_volume":            cv,
                        "component_effective_profit":  round(comp_eff, 4),
                        "weighted_effective_profit":   round(w * comp_eff, 4),
                        "component_source_profit":     round(src, 4),
                        "component_operational_cost":  round(op, 4),
                        "component_revenue":           round(rev, 4),
                        "component_domain_response":   round(credit - decay, 4),
                        "component_within_addressable": within,
                    })
                    w_eff    += w * comp_eff
                    w_src    += w * src
                    w_op     += w * op
                    w_rev    += w * rev
                    w_credit += w * credit
                    w_decay  += w * decay
                    w_be     += w * r["break_even_rate"]

                if incomplete:
                    continue

                best  = max(comp_details, key=lambda c: c["component_effective_profit"])
                worst = min(comp_details, key=lambda c: c["component_effective_profit"])
                out.append({
                    "service_mix_name":               mix_name,
                    "capacity_model":                 cap,
                    "deliveries_per_day":             total_v,
                    "component_count":                len(comp_details),
                    "components":                     comp_details,
                    "avg_effective_profit":           round(w_eff, 4),
                    "avg_source_profit":              round(w_src, 4),
                    "avg_operational_cost":           round(w_op, 4),
                    "avg_revenue":                    round(w_rev, 4),
                    "capacity_overhead_per_delivery": round(shared_overhead, 4),
                    "domain_efficiency_credit":       round(w_credit, 4),
                    "domain_value_decay":             round(w_decay, 4),
                    "net_domain_response":            round(w_credit - w_decay, 4),
                    # Weight-weighted mean of component break-even rates at
                    # their component volumes.  Documented approximation —
                    # a single "break-even rate" for a blended portfolio
                    # has no exact analog.
                    "break_even_rate":                round(w_be, 4),
                    "within_addressable_demand":      all_within,
                    "best_component_domain":          best["component_domain"],
                    "worst_component_domain":         worst["component_domain"],
                })
    return out


def best_worst_service_mix(
    db_path: str,
    capacity_model: Optional[str] = None,
    deliveries_per_day: Optional[int] = None,
) -> dict:
    """Compact best/worst summary for the portfolio-summary surface.

    Picks a single representative volume (the median of the default
    sweep) and the default capacity unless overridden.  Also flags, per
    mix, whether the blend beats its own weakest component at that point.
    """
    cap = capacity_model or DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY
    if deliveries_per_day is None:
        sweep = list(DEFAULT_DELIVERIES_PER_DAY_SWEEP)
        deliveries_per_day = sweep[len(sweep) // 2]   # representative mid-volume

    rows = compute_service_mix_summary(
        db_path,
        capacity_model_names      = [cap],
        deliveries_per_day_values = [deliveries_per_day],
    )
    if not rows:
        return {
            "capacity_model":     cap,
            "deliveries_per_day": deliveries_per_day,
            "rows":               [],
            "best":               None,
            "worst":              None,
        }

    compact = []
    for r in rows:
        comp_effs = [c["component_effective_profit"] for c in r["components"]]
        weakest_component = min(comp_effs)
        compact.append({
            "service_mix_name":      r["service_mix_name"],
            "avg_effective_profit":  r["avg_effective_profit"],
            "weakest_component_effective_profit": round(weakest_component, 4),
            "beats_weakest_component": r["avg_effective_profit"] > weakest_component,
            "best_component_domain":  r["best_component_domain"],
            "worst_component_domain": r["worst_component_domain"],
        })

    best  = max(compact, key=lambda c: c["avg_effective_profit"])
    worst = min(compact, key=lambda c: c["avg_effective_profit"])
    return {
        "capacity_model":     cap,
        "deliveries_per_day": deliveries_per_day,
        "rows":               compact,
        "best":               best,
        "worst":              worst,
    }
