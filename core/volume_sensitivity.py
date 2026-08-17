"""
core/volume_sensitivity.py

Volume sensitivity analysis for scale economics.

Two formulas live in this module:

1. ``volume_sensitivity`` — **capacity-coupled** (Phase 28, current).
   Given deliveries_per_day, derive required drones / operators /
   chargers / maintenance staff from a :class:`CapacityModel`, sum the
   daily costs, divide by volume.  This is the model the workbench
   surfaces.

2. ``legacy_fixed_overhead_sensitivity`` — **fixed-overhead** (Phase 27,
   predecessor).  Holds the entire daily overhead constant and divides
   by deliveries_per_day.  Preserved for posterity and for the
   Phase 27 chart artifact; not routed through the API.

Why deliveries-per-day, not fleet_size
───────────────────────────────────────
``fleet_size`` is a capacity proxy.  ``deliveries_per_day`` is the
demand quantity that determines how much capacity you need.  Sweeping
volume directly is the right framing; capacity (and the costs that
follow from it) should be derived, not asserted.

Capacity-coupled formula (Phase 28) + domain response (Phase 29)
─────────────────────────────────────────────────────────────────
For each sweep point ``d`` (deliveries/day), each :class:`CapacityModel`
``cm``, and each :class:`DeliveryDomain` ``dom``::

    # Capacity (Phase 28).
    required_drones      = ceil(d / cm.deliveries_per_drone_per_day)
    required_operators   = ceil(required_drones * cm.operator_to_drone_ratio)
    required_maintenance = ceil(required_drones * cm.maintenance_staff_per_drone)
    required_chargers    = ceil(required_drones * cm.charger_to_drone_ratio)

    daily_capacity_overhead =
          cm.platform_fixed_cost_usd_day
        + required_drones      * cm.drone_daily_lease_or_depreciation_usd
        + required_operators   * cm.operator_daily_cost_usd
        + required_maintenance * cm.maintenance_daily_cost_usd
        + required_chargers    * cm.charger_daily_cost_usd

    capacity_overhead_per_delivery = daily_capacity_overhead / d

    # Domain response (Phase 29) — both bounded by the domain's
    # saturation_volume_per_day; see docstrings on the helpers below.
    efficiency_credit = domain_efficiency_credit(d, avg_op_cost, dom)
    value_decay       = domain_value_decay      (d, avg_revenue, dom)

    # Effective profit derived from adjusted revenue/cost decomposition.
    adjusted_revenue  = avg_revenue          - value_decay
    adjusted_op_cost  = avg_operational_cost - efficiency_credit
    effective_profit  = adjusted_revenue - adjusted_op_cost
                      - capacity_overhead_per_delivery

No utilization rebate is added.  See ``core/capacity_models.py``
docstring for the rationale.

Caveats
───────
* The chart curves are **staircase functions** of ``deliveries_per_day``
  because every ``required_*`` quantity is integer-valued — Phase 28's
  correction.  Phase 29 layers a smooth log-saturating efficiency credit
  and a linear-to-saturation value decay on top.  The composite chart
  therefore shows three effects superimposed; the decomposition chart
  (``domain_response_components_by_volume.png``) separates them.

* Domain volume response is **synthetic** — a comparative assumption
  layer, not measured demand elasticity.  Both response terms are
  bounded above by ``rate × baseline``; neither grows without limit.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import replace
from typing import Optional

from core.capacity_models import (
    CAPACITY_MODEL_REGISTRY_VERSION, CapacityModel, get_capacity_model,
)
from core.delivery_domains import (
    DELIVERY_DOMAIN_REGISTRY_VERSION, DeliveryDomain, get_domain,
)
from core.scale_models import (
    SCALE_MODEL_REGISTRY_VERSION, ScaleModel, get_scale_model,
)


# 12 points spanning pilot-scale through national-scale, roughly
# log-spaced.  Pinned in code so the chart x-axis is reproducible.
DEFAULT_DELIVERIES_PER_DAY_SWEEP: list[int] = [
    25, 50, 100, 150, 250, 400,
    650, 1000, 1500, 2500, 4000, 6000,
]

# Default capacity model = pilot_capacity.  Same conservative-baseline
# logic Phase 27 used: start from the smallest-fleet cost structure so
# the chart does not pre-bias the reader toward an optimistic regime.
DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY = "pilot_capacity"


# ─────────────────────────────────────────────────────────────────────────────
# Shared: pulling the source economics snapshots
# ─────────────────────────────────────────────────────────────────────────────

def _select_latest_economics_per_trip_domain(
    conn: sqlite3.Connection,
    *,
    source_snapshot_run_id: Optional[str],
    delivery_domains:       Optional[list[str]],
) -> list[tuple]:
    """Return (trip_id, domain_name, estimated_profit,
    estimated_operational_cost, estimated_revenue) for the most-recent
    (trip, domain) snapshot in ``trip_economics_snapshots``.  Same
    convention as the matrix and delivery-domains endpoints so all three
    views compose cleanly.
    """
    if source_snapshot_run_id is not None:
        sql = """
            SELECT trip_id, domain_name, estimated_profit,
                   estimated_operational_cost, estimated_revenue
              FROM trip_economics_snapshots
             WHERE transform_run_id = ? AND domain_name IS NOT NULL
        """
        rows = conn.execute(sql, (source_snapshot_run_id,)).fetchall()
    else:
        sql = """
            WITH ranked AS (
                SELECT trip_id, domain_name, estimated_profit,
                       estimated_operational_cost, estimated_revenue,
                       ROW_NUMBER() OVER (
                           PARTITION BY trip_id, domain_name
                           ORDER BY created_at DESC
                       ) AS rk
                  FROM trip_economics_snapshots
                 WHERE domain_name IS NOT NULL
            )
            SELECT trip_id, domain_name, estimated_profit,
                   estimated_operational_cost, estimated_revenue
              FROM ranked WHERE rk = 1
        """
        rows = conn.execute(sql).fetchall()

    if delivery_domains:
        wanted = set(delivery_domains)
        rows = [r for r in rows if r[1] in wanted]
    return rows


def _bucket_by_domain(
    rows: list[tuple],
) -> dict[str, list[tuple[float, float, float]]]:
    """Group source-economics tuples by domain →
    [(source_profit, op_cost, revenue), …]."""
    bucket: dict[str, list[tuple[float, float, float]]] = {}
    for _trip_id, domain, profit, op_cost, revenue in rows:
        bucket.setdefault(domain, []).append((
            float(profit  or 0.0),
            float(op_cost or 0.0),
            float(revenue or 0.0),
        ))
    return bucket


# ─────────────────────────────────────────────────────────────────────────────
# Phase 29: domain volume-response helpers
#
# Both are pure functions; both are bounded above by ``rate × baseline``.
# Neither grows without limit — the prompt asks for "no unbounded runaway
# gains" and these helpers achieve that by saturating at the domain's
# saturation_volume_per_day rather than by relying on the sweep ending.
# ─────────────────────────────────────────────────────────────────────────────

def domain_efficiency_credit(
    *,
    deliveries_per_day:   int,
    avg_operational_cost: float,
    domain:               DeliveryDomain,
) -> float:
    """Cost-side credit: a fraction of operational cost recovered as
    volume rises (routing density, shared maintenance, etc.).

    Bounded above by ``avg_operational_cost × volume_efficiency_gain_rate``.
    Reaches that bound when ``deliveries_per_day ≥ saturation_volume_per_day``.
    Below that, growth is log-saturating: rapid early gains, flattens
    out as the domain approaches its addressable ceiling.

    Saturation normalization
    ────────────────────────
    The raw ``log1p(d/100)`` grows without limit, so we normalize by
    the same quantity evaluated at ``saturation_volume_per_day``::

        progress = min(1.0, log1p(d/100) / log1p(saturation/100))

    Then ``credit = avg_op_cost × rate × progress``.  This produces a
    fast initial rise, gradual flattening, and a hard cap at saturation.
    """
    if deliveries_per_day <= 0 or domain.saturation_volume_per_day <= 0:
        return 0.0
    log_now = math.log1p(deliveries_per_day        / 100.0)
    log_sat = math.log1p(domain.saturation_volume_per_day / 100.0)
    if log_sat <= 0:
        return 0.0
    progress = min(1.0, log_now / log_sat)
    return avg_operational_cost * domain.volume_efficiency_gain_rate * progress


def domain_value_decay(
    *,
    deliveries_per_day: int,
    avg_revenue:        float,
    domain:             DeliveryDomain,
) -> float:
    """Revenue-side dilution: a fraction of revenue lost as lower-priority
    volume enters the mix and the average customer's willingness-to-pay
    drops.

    Bounded above by ``avg_revenue × volume_value_decay_rate``.  Reaches
    that bound when ``deliveries_per_day ≥ saturation_volume_per_day``.
    Below that, growth is linear in volume.  Above saturation, the
    decay is flat — further volume cannot dilute premium beyond what's
    already been diluted.
    """
    if deliveries_per_day <= 0 or domain.saturation_volume_per_day <= 0:
        return 0.0
    progress = min(1.0, deliveries_per_day / domain.saturation_volume_per_day)
    return avg_revenue * domain.volume_value_decay_rate * progress


# ─────────────────────────────────────────────────────────────────────────────
# Capacity-coupled (Phase 28 — primary)
# ─────────────────────────────────────────────────────────────────────────────

def capacity_overhead_per_delivery(capacity_model, deliveries_per_day: int) -> float:
    """Public helper: per-delivery capacity overhead for a capacity model
    at a given total volume.  Domain-independent, no DB needed.

    Used by service-mix analysis (Phase 33) to apply ONE shared fleet
    overhead at the mix's total volume rather than per-component.
    """
    cm = get_capacity_model(capacity_model)
    if deliveries_per_day <= 0:
        return 0.0
    return _required_capacity(cm, deliveries_per_day)["daily_capacity_overhead"] \
        / deliveries_per_day


def _required_capacity(cm: CapacityModel, d: int) -> dict:
    """Pure capacity arithmetic — no DB, no economics."""
    required_drones      = math.ceil(d / cm.deliveries_per_drone_per_day)
    required_operators   = math.ceil(required_drones * cm.operator_to_drone_ratio)
    required_maintenance = math.ceil(required_drones * cm.maintenance_staff_per_drone)
    required_chargers    = math.ceil(required_drones * cm.charger_to_drone_ratio)
    daily_overhead = (
        cm.platform_fixed_cost_usd_day
        + required_drones      * cm.drone_daily_lease_or_depreciation_usd
        + required_operators   * cm.operator_daily_cost_usd
        + required_maintenance * cm.maintenance_daily_cost_usd
        + required_chargers    * cm.charger_daily_cost_usd
    )
    return {
        "required_drones":             int(required_drones),
        "required_operators":          int(required_operators),
        "required_maintenance_staff":  int(required_maintenance),
        "required_chargers":           int(required_chargers),
        "daily_capacity_overhead":     float(daily_overhead),
    }


def volume_sensitivity(
    db_path: str,
    *,
    source_snapshot_run_id:    Optional[str]       = None,
    capacity_model:            str                 = DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY,
    delivery_domains:          Optional[list[str]] = None,
    deliveries_per_day_points: Optional[list[int]] = None,
) -> list[dict]:
    """Capacity-coupled volume sweep.

    For each (domain, deliveries_per_day) cell, derive required capacity
    from the :class:`CapacityModel`, sum daily costs, and recompute
    effective profit per trip using the trips' source economics
    snapshots.

    Args:
        db_path:                   SQLite file.
        source_snapshot_run_id:    Pin to one economics transform_run_id.
                                   ``None`` → most-recent snapshot per
                                   (trip, domain).
        capacity_model:            Cost-structure / productivity template.
                                   Default: ``pilot_capacity``.
        delivery_domains:          Restrict to these domains.  ``None``
                                   → every domain found.
        deliveries_per_day_points: Sweep grid.  ``None`` →
                                   :data:`DEFAULT_DELIVERIES_PER_DAY_SWEEP`.

    Returns:
        list of row dicts, sorted by (delivery_domain ASC,
        deliveries_per_day ASC), with keys::

            delivery_domain                  str
            capacity_model                   str
            deliveries_per_day               int

            # Capacity (Phase 28)
            required_drones                  int
            required_operators               int
            required_maintenance_staff       int
            required_chargers                int
            daily_capacity_overhead          float
            capacity_overhead_per_delivery   float

            # Source economics
            avg_operational_cost             float
            avg_revenue                      float
            avg_source_profit                float

            # Domain volume response (Phase 29)
            saturation_volume_per_day        int
            domain_efficiency_credit         float  (≥ 0; bounded)
            domain_value_decay               float  (≥ 0; bounded)
            net_domain_response              float  (= credit − decay)
            adjusted_avg_operational_cost    float  (avg_op_cost − credit)
            adjusted_avg_revenue             float  (avg_revenue − decay)

            # Composite
            avg_effective_profit             float
            break_even_rate                  float [0..1]
            trip_count                       int
    """
    cm    = get_capacity_model(capacity_model)
    sweep = list(deliveries_per_day_points or DEFAULT_DELIVERIES_PER_DAY_SWEEP)

    conn = sqlite3.connect(db_path)
    try:
        sources = _select_latest_economics_per_trip_domain(
            conn,
            source_snapshot_run_id = source_snapshot_run_id,
            delivery_domains       = delivery_domains,
        )
    finally:
        conn.close()
    by_domain = _bucket_by_domain(sources)

    rows: list[dict] = []
    for domain_name in sorted(by_domain.keys()):
        trips = by_domain[domain_name]
        n = len(trips)
        if n == 0:
            continue
        # Resolve the DeliveryDomain so we can read its response knobs.
        # KeyError here is a real data problem — the snapshot references
        # an unknown domain — so let it propagate.
        dom = get_domain(domain_name)
        # Pre-compute domain-level source aggregates once.
        sum_op   = sum(op   for _p, op,  _r in trips)
        sum_prof = sum(prof for prof, _o, _r in trips)
        sum_rev  = sum(rev  for _p, _o, rev  in trips)
        avg_op   = sum_op   / n
        avg_prof = sum_prof / n
        avg_rev  = sum_rev  / n
        for d in sweep:
            cap = _required_capacity(cm, d)
            overhead_per = cap["daily_capacity_overhead"] / d if d > 0 else 0.0

            # Phase 29 response terms — pure functions of (d, domain, avg_*).
            credit = domain_efficiency_credit(
                deliveries_per_day   = d,
                avg_operational_cost = avg_op,
                domain               = dom,
            )
            decay = domain_value_decay(
                deliveries_per_day = d,
                avg_revenue        = avg_rev,
                domain             = dom,
            )

            # Adjusted-revenue / adjusted-cost decomposition.  Equivalent
            # to (source_profit + credit - decay) - overhead, but with
            # the audit trail of each per-trip dollar visible.
            adj_revenue = avg_rev - decay
            adj_op      = avg_op  - credit
            avg_eff     = adj_revenue - adj_op - overhead_per
            # Per-trip break-even check uses each trip's source profit
            # plus the (domain-uniform) response and overhead deltas.
            # delta_per_trip = credit - decay - overhead_per is constant
            # across trips within this cell.
            delta = credit - decay - overhead_per
            above_zero = sum(
                1 for prof, _op, _rev in trips if (prof + delta) > 0
            )
            rows.append({
                "delivery_domain":                 domain_name,
                "capacity_model":                  cm.name,
                "deliveries_per_day":              int(d),

                # Capacity (Phase 28)
                "required_drones":                 cap["required_drones"],
                "required_operators":              cap["required_operators"],
                "required_maintenance_staff":      cap["required_maintenance_staff"],
                "required_chargers":               cap["required_chargers"],
                "daily_capacity_overhead":         round(cap["daily_capacity_overhead"], 4),
                "capacity_overhead_per_delivery":  round(overhead_per, 4),

                # Source economics
                "avg_operational_cost":            round(avg_op,   4),
                "avg_revenue":                     round(avg_rev,  4),
                "avg_source_profit":               round(avg_prof, 4),

                # Domain volume response (Phase 29)
                "saturation_volume_per_day":       dom.saturation_volume_per_day,
                "domain_efficiency_credit":        round(credit, 4),
                "domain_value_decay":              round(decay,  4),
                "net_domain_response":             round(credit - decay, 4),
                "adjusted_avg_operational_cost":   round(adj_op,      4),
                "adjusted_avg_revenue":            round(adj_revenue, 4),

                # Phase 29 revision: addressable-demand flag.  False
                # means the sweep point is past the domain's modeled
                # addressable demand — the row is still computed (the
                # response terms have already saturated) but charts and
                # tables should render it as extrapolation.
                "within_addressable_demand":       d <= dom.saturation_volume_per_day,

                # Composite
                "avg_effective_profit":            round(avg_eff,  4),
                "break_even_rate":                 round(above_zero / n, 4),
                "trip_count":                      n,
            })
    return rows


def sensitivity_metadata(
    capacity_model: str = DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY,
) -> dict:
    """Capacity-coupled metadata for UI / chart captions.

    Returned alongside the row data so a reviewer can see exactly what
    assumptions produced the curve — productivity rate, staffing
    ratios, per-resource daily costs, registry version.
    """
    cm = get_capacity_model(capacity_model)
    return {
        "capacity_model_name":          cm.name,
        "deliveries_per_drone_per_day": cm.deliveries_per_drone_per_day,
        "operator_to_drone_ratio":      cm.operator_to_drone_ratio,
        "maintenance_staff_per_drone":  cm.maintenance_staff_per_drone,
        "charger_to_drone_ratio":       cm.charger_to_drone_ratio,
        "platform_fixed_cost_usd_day":  cm.platform_fixed_cost_usd_day,
        "operator_daily_cost_usd":      cm.operator_daily_cost_usd,
        "maintenance_daily_cost_usd":   cm.maintenance_daily_cost_usd,
        "charger_daily_cost_usd":       cm.charger_daily_cost_usd,
        "drone_daily_lease_or_depreciation_usd":
                                        cm.drone_daily_lease_or_depreciation_usd,
        "sweep_points":                 list(DEFAULT_DELIVERIES_PER_DAY_SWEEP),
        "registry_version":             CAPACITY_MODEL_REGISTRY_VERSION,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Legacy fixed-overhead sensitivity (Phase 27 — predecessor)
# Kept for posterity and so the Phase 27 chart artifact still renders.
# Not routed through the API.  Do not use in new code; switch to
# ``volume_sensitivity`` above.
# ─────────────────────────────────────────────────────────────────────────────

def _legacy_clone_scale_model_at_volume(sm: ScaleModel, deliveries_per_day: int) -> ScaleModel:
    return replace(sm, deliveries_per_day=int(deliveries_per_day))


def _legacy_effective_profit(
    *, source_profit: float, source_op_cost: float, sm: ScaleModel,
) -> float:
    """Phase 27 / Phase 23 formula — overhead amortization + utilization
    rebate.  Carried forward only for the legacy sensitivity below."""
    overhead = sm.amortized_overhead_per_trip()
    rebate   = sm.utilization_efficiency * sm.idle_reduction_factor * source_op_cost
    return source_profit - overhead + rebate


def legacy_fixed_overhead_sensitivity(
    db_path: str,
    *,
    source_snapshot_run_id:    Optional[str]       = None,
    scale_model:               str                 = "pilot_program",
    delivery_domains:          Optional[list[str]] = None,
    deliveries_per_day_points: Optional[list[int]] = None,
) -> list[dict]:
    """Phase 27 fixed-overhead sweep (predecessor of
    :func:`volume_sensitivity`).

    Holds the entire daily overhead constant and divides by the swept
    deliveries_per_day.  Does not couple capacity to volume — kept for
    posterity and so the Phase 27 chart artifact still renders.  Do
    **not** consume in new code.
    """
    sm    = get_scale_model(scale_model)
    sweep = list(deliveries_per_day_points or DEFAULT_DELIVERIES_PER_DAY_SWEEP)

    conn = sqlite3.connect(db_path)
    try:
        sources = _select_latest_economics_per_trip_domain(
            conn,
            source_snapshot_run_id = source_snapshot_run_id,
            delivery_domains       = delivery_domains,
        )
    finally:
        conn.close()
    by_domain = _bucket_by_domain(sources)

    rows: list[dict] = []
    for domain in sorted(by_domain.keys()):
        trips = by_domain[domain]
        n = len(trips)
        if n == 0:
            continue
        for d in sweep:
            cloned = _legacy_clone_scale_model_at_volume(sm, d)
            overhead = cloned.amortized_overhead_per_trip()
            total_op   = 0.0
            total_prof = 0.0
            above_zero = 0
            for source_profit, source_op_cost, _source_revenue in trips:
                eff = _legacy_effective_profit(
                    source_profit  = source_profit,
                    source_op_cost = source_op_cost,
                    sm             = cloned,
                )
                total_op   += source_op_cost
                total_prof += eff
                if eff > 0:
                    above_zero += 1
            rows.append({
                "delivery_domain":         domain,
                "scale_model":             sm.name,
                "deliveries_per_day":      int(d),
                "avg_operational_cost":    round(total_op   / n, 4),
                "avg_amortized_overhead":  round(overhead,       4),
                "avg_effective_profit":    round(total_prof / n, 4),
                "break_even_rate":         round(above_zero / n, 4),
                "trip_count":              n,
            })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Phase 29 rev: viability summary across (capacity_model × delivery_domain)
# ─────────────────────────────────────────────────────────────────────────────

def compute_viability_summary(
    db_path: str,
    *,
    capacity_models:           Optional[list[str]] = None,
    delivery_domains:          Optional[list[str]] = None,
    source_snapshot_run_id:    Optional[str]       = None,
    deliveries_per_day_points: Optional[list[int]] = None,
) -> list[dict]:
    """Cross-tabulation: for every (capacity_model, delivery_domain) cell,
    determine whether the model finds break-even at any sweep point and
    whether that break-even sits within the domain's addressable demand.

    Args:
        db_path:                   SQLite file.
        capacity_models:           Restrict to these capacity models;
                                   ``None`` → every one registered.
        delivery_domains:          Restrict to these domains; ``None`` →
                                   every domain found in the data.
        source_snapshot_run_id:    Forwarded to ``volume_sensitivity``.
        deliveries_per_day_points: Forwarded to ``volume_sensitivity``.

    Returns:
        list of cell dicts with keys::

            capacity_model                   str
            delivery_domain                  str
            addressable_ceiling              int   (= saturation_volume_per_day)
            breakeven_deliveries_per_day     int | None
            viable_within_addressable_demand bool

        ``breakeven_deliveries_per_day`` is the smallest sweep point at
        which ``avg_effective_profit > 0`` for that (capacity, domain)
        pair — regardless of whether it falls within or beyond the
        addressable ceiling.  ``None`` if no sweep point clears zero.

        ``viable_within_addressable_demand`` is True iff
        ``breakeven_deliveries_per_day`` is not None AND
        ``breakeven_deliveries_per_day <= addressable_ceiling``.

    Read-only — no writes; just summarizes what ``volume_sensitivity``
    would already produce per capacity model.
    """
    # Late import to keep the public ``list_capacity_models`` symbol
    # available without a circular import through ``core.capacity_models``.
    from core.capacity_models import list_capacity_models

    # Phase 32 / addendum: when no explicit list is given, the axes are
    # the registered profiles PLUS only the SINGLE most-recent what-if's
    # synthetic variants — not every experiment ever run.  Three what-ifs
    # in a row therefore keep the grid a fixed, readable size; only the
    # latest one's variants appear.  ``recent_domains`` is used below to
    # drop stale synthetic-domain cells that still live in snapshot data.
    from core.experiments import most_recent_experiment_synthetics
    if capacity_models:
        capacities = list(capacity_models)
        recent_domains = None   # caller is explicit; don't scope domains
    else:
        recent = most_recent_experiment_synthetics(db_path)
        capacities = list_capacity_models() + recent["capacity_model"]
        # Only scope synthetic domains once a sweep-bearing experiment
        # exists.  Before any experiment, ambient synthetic domains in
        # snapshots are shown as-is (preserves the pre-addendum contract).
        has_recent = bool(recent["delivery_domain"] or recent["capacity_model"])
        recent_domains = set(recent["delivery_domain"]) if has_recent else None

    cells: list[dict] = []
    for cm_name in capacities:
        rows = volume_sensitivity(
            db_path,
            capacity_model            = cm_name,
            delivery_domains          = delivery_domains,
            source_snapshot_run_id    = source_snapshot_run_id,
            deliveries_per_day_points = deliveries_per_day_points,
        )
        # Group this capacity model's rows by domain.  When scoping is
        # active (no explicit domain filter), drop synthetic-domain rows
        # that aren't from the most-recent experiment — their snapshots
        # persist forever but we only want base domains + the latest sweep.
        by_domain: dict[str, list[dict]] = {}
        for r in rows:
            dom = r["delivery_domain"]
            if (recent_domains is not None and delivery_domains is None
                    and "@" in dom and dom not in recent_domains):
                continue
            by_domain.setdefault(dom, []).append(r)

        for dom_name in sorted(by_domain.keys()):
            dom_rows = sorted(
                by_domain[dom_name], key=lambda r: r["deliveries_per_day"]
            )
            ceiling = int(dom_rows[0]["saturation_volume_per_day"])
            breakeven_d: Optional[int] = None
            for r in dom_rows:
                if r["avg_effective_profit"] > 0:
                    breakeven_d = int(r["deliveries_per_day"])
                    break
            cells.append({
                "capacity_model":                   cm_name,
                "delivery_domain":                  dom_name,
                "addressable_ceiling":              ceiling,
                "breakeven_deliveries_per_day":     breakeven_d,
                "viable_within_addressable_demand": (
                    breakeven_d is not None and breakeven_d <= ceiling
                ),
            })
    return cells


def viability_state(cell: dict) -> str:
    """Map a viability cell to a categorical state used by charts + UI.

    Returns one of:
      * ``"viable"``  — breakeven exists AND sits within addressable demand
      * ``"beyond"``  — breakeven exists but only past the addressable ceiling
      * ``"never"``   — no sweep point clears zero
    """
    be = cell["breakeven_deliveries_per_day"]
    if be is None:
        return "never"
    if be <= cell["addressable_ceiling"]:
        return "viable"
    return "beyond"


def legacy_sensitivity_metadata(scale_model: str = "pilot_program") -> dict:
    """Phase 27 metadata helper — kept for the legacy chart only."""
    sm = get_scale_model(scale_model)
    return {
        "scale_model_name":             sm.name,
        "daily_overhead_usd":           round(sm.daily_overhead_usd(), 2),
        "utilization_efficiency":       sm.utilization_efficiency,
        "idle_reduction_factor":        sm.idle_reduction_factor,
        "sweep_points":                 list(DEFAULT_DELIVERIES_PER_DAY_SWEEP),
        "registry_version":             SCALE_MODEL_REGISTRY_VERSION,
    }
