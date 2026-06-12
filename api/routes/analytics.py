"""GET /analytics/delivery-displacement — the headline business endpoint."""

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from api.dependencies import require_db
from core.displacement import (
    DEFAULT_TRUCK_COST_PER_DELIVERY, compute_delivery_displacement,
)
from core.hybrid_analytics import (
    activation_reasons, hybrid_summary, latency_by_mode,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/delivery-displacement")
def delivery_displacement(
    truck_cost_per_delivery: float = DEFAULT_TRUCK_COST_PER_DELIVERY,
    db: str = Depends(require_db),
) -> dict:
    """Synthetic deliveries displaced + estimated cost difference.

    Query param ``truck_cost_per_delivery`` lets the frontend explore
    different truck-cost assumptions without rerunning the simulator.
    """
    return compute_delivery_displacement(db, truck_cost_per_delivery)


# ── Phase 19: hybrid logistics endpoints ────────────────────────────────────

@router.get("/hybrid-summary")
def hybrid_summary_endpoint(db: str = Depends(require_db)) -> dict:
    """Per-scenario fulfillment-mode split + latency comparison."""
    return hybrid_summary(db)


@router.get("/latency")
def latency_endpoint(db: str = Depends(require_db)) -> dict:
    """Average latency by fulfillment mode + trucks-only/drones-only/hybrid strategy."""
    return latency_by_mode(db)


@router.get("/activation-reasons")
def activation_reasons_endpoint(db: str = Depends(require_db)) -> dict:
    """Counts of individual reasons that fired across all orders, plus per-mode breakdown."""
    return activation_reasons(db)


# ── Phase 21: telemetry endpoints ───────────────────────────────────────────

@router.get("/telemetry-summary")
def telemetry_summary_endpoint(db: str = Depends(require_db)) -> dict:
    """Per-scenario telemetry aggregates straight from the raw observations."""
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT de.scenario_name,
                   COUNT(*),
                   AVG(t.altitude_m), AVG(t.airspeed_mps),
                   AVG(t.battery_temp_c), MAX(t.battery_temp_c),
                   AVG(t.motor_temp_c),   MAX(t.motor_temp_c),
                   AVG(t.signal_strength_pct), AVG(t.gps_signal_quality),
                   AVG(t.estimated_remaining_range_km)
              FROM delivery_events de
              JOIN telemetry_observations t ON t.event_id = de.event_id
             WHERE de.scenario_name IS NOT NULL
             GROUP BY de.scenario_name
             ORDER BY de.scenario_name ASC
            """
        ).fetchall()
    finally:
        conn.close()
    return {
        "by_scenario": [
            {
                "scenario_name":              r[0],
                "pings":                      int(r[1] or 0),
                "avg_altitude_m":             round(r[2] or 0.0, 2),
                "avg_airspeed_mps":           round(r[3] or 0.0, 2),
                "avg_battery_temp_c":         round(r[4] or 0.0, 2),
                "max_battery_temp_c":         round(r[5] or 0.0, 2),
                "avg_motor_temp_c":           round(r[6] or 0.0, 2),
                "max_motor_temp_c":           round(r[7] or 0.0, 2),
                "avg_signal_pct":             round(r[8] or 0.0, 2),
                "avg_gps_quality":            round(r[9] or 0.0, 2),
                "avg_remaining_range_km":     round(r[10] or 0.0, 3),
            }
            for r in rows
        ],
    }


# ── Phase 22: delivery-domain reinterpretation ──────────────────────────────

@router.get("/delivery-domains")
def delivery_domains_endpoint(db: str = Depends(require_db)) -> dict:
    """Return the registered delivery-domain profiles + the most recent
    snapshot per (scenario, domain) joined to ``transformation_runs``
    for lineage.

    No state mutation — this is a read-only window into what's already
    been recomputed.  To produce a new snapshot, call
    ``transforms/economics.run(delivery_domain=...)`` and refresh.
    """
    import sqlite3
    from core.delivery_domains import (
        DELIVERY_DOMAIN_REGISTRY_VERSION, get_domain, list_domains,
    )
    profiles = [get_domain(name).to_dict() for name in list_domains()]
    conn = sqlite3.connect(db)
    try:
        # Most-recent snapshot per (scenario, domain).  SQLite's
        # ROW_NUMBER() is available from 3.25 (we target 3.35+).
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT t.scenario_name,
                       s.domain_name,
                       s.transform_run_id,
                       s.created_at,
                       AVG(s.estimated_revenue)             AS avg_revenue,
                       AVG(s.estimated_operational_cost)    AS avg_op_cost,
                       AVG(s.estimated_profit)              AS avg_profit,
                       COUNT(*)                             AS snapshot_count,
                       ROW_NUMBER() OVER (
                           PARTITION BY t.scenario_name, s.domain_name
                           ORDER BY s.created_at DESC
                       )                                    AS rk
                  FROM trip_economics_snapshots s
                  JOIN trips t ON t.trip_id = s.trip_id
                 WHERE s.domain_name IS NOT NULL
                 GROUP BY t.scenario_name, s.domain_name, s.transform_run_id,
                          s.created_at
            )
            SELECT scenario_name, domain_name, transform_run_id, created_at,
                   avg_revenue, avg_op_cost, avg_profit, snapshot_count
              FROM ranked WHERE rk = 1
             ORDER BY scenario_name ASC, domain_name ASC
            """
        ).fetchall()
    finally:
        conn.close()
    return {
        "registry_version": DELIVERY_DOMAIN_REGISTRY_VERSION,
        "profiles":         profiles,
        "latest_snapshots": [
            {
                "scenario_name":     r[0],
                "domain_name":       r[1],
                "transform_run_id":  r[2],
                "computed_at":       r[3],
                "avg_revenue_per_trip":           round(float(r[4] or 0), 2),
                "avg_operational_cost_per_trip": round(float(r[5] or 0), 2),
                "avg_profit_per_trip":           round(float(r[6] or 0), 2),
                "snapshot_count":    int(r[7] or 0),
            }
            for r in rows
        ],
    }


# ── Phase 23: scale-model amortization ──────────────────────────────────────

@router.get("/scale-models")
def scale_models_endpoint(db: str = Depends(require_db)) -> dict:
    """Return the registered scale profiles + the most recent snapshot
    rollup per (scale_model, scenario), joined to ``transformation_runs``
    for lineage.

    Read-only.  To produce a new snapshot, call
    ``transforms/scale.run(scale_model=...)`` and refresh.
    """
    import sqlite3
    from core.scale_models import (
        SCALE_MODEL_REGISTRY_VERSION, get_scale_model, list_scale_models,
    )
    profiles = [get_scale_model(name).to_dict() for name in list_scale_models()]
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT t.scenario_name,
                       s.scale_model_name,
                       s.transform_run_id,
                       s.created_at,
                       AVG(e.estimated_operational_cost)    AS avg_op_cost,
                       AVG(s.amortized_overhead_per_trip)   AS avg_overhead,
                       AVG(s.effective_profit)              AS avg_effective_profit,
                       SUM(CASE WHEN s.effective_profit > 0 THEN 1 ELSE 0 END)
                                                            AS trips_break_even,
                       COUNT(*)                             AS snapshot_count,
                       ROW_NUMBER() OVER (
                           PARTITION BY t.scenario_name, s.scale_model_name
                           ORDER BY s.created_at DESC
                       ) AS rk
                  FROM trip_scale_snapshots s
                  JOIN trip_economics_snapshots e
                       ON  e.transform_run_id = s.source_snapshot_run_id
                       AND e.trip_id          = s.trip_id
                  JOIN trips t ON t.trip_id = s.trip_id
                 GROUP BY t.scenario_name, s.scale_model_name,
                          s.transform_run_id, s.created_at
            )
            SELECT scenario_name, scale_model_name, transform_run_id,
                   created_at, avg_op_cost, avg_overhead,
                   avg_effective_profit, trips_break_even, snapshot_count
              FROM ranked WHERE rk = 1
             ORDER BY scenario_name ASC, scale_model_name ASC
            """
        ).fetchall()
    finally:
        conn.close()
    return {
        "registry_version": SCALE_MODEL_REGISTRY_VERSION,
        "profiles":         profiles,
        "latest_snapshots": [
            {
                "scenario_name":            r[0],
                "scale_model_name":         r[1],
                "transform_run_id":         r[2],
                "computed_at":              r[3],
                "avg_operational_cost":     round(float(r[4] or 0), 2),
                "avg_amortized_overhead":   round(float(r[5] or 0), 2),
                "avg_effective_profit":     round(float(r[6] or 0), 2),
                "trips_break_even":         int(r[7] or 0),
                "snapshot_count":           int(r[8] or 0),
            }
            for r in rows
        ],
    }


# ── Phase 26: domain × scale cross-section (UI-facing) ──────────────────────

@router.get("/domain-scale-matrix")
def domain_scale_matrix_endpoint(db: str = Depends(require_db)) -> dict:
    """Cross-section of the most recent (scenario, domain, scale_model)
    snapshot triples.  Built directly from snapshot tables — no experiment
    required — so the UI can render the matrix on bare run data.

    Each cell summarises one (scenario, domain, scale_model) tuple using
    the most-recent transformation_runs lineage chain.  Used by the
    workbench's Domain & Scale Analysis page.
    """
    import sqlite3
    from core.delivery_domains import list_domains
    from core.scale_models    import list_scale_models

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            WITH joined AS (
                SELECT t.scenario_name,
                       e.domain_name,
                       s.scale_model_name,
                       s.transform_run_id           AS scale_tx_id,
                       e.transform_run_id           AS econ_tx_id,
                       s.created_at,
                       e.estimated_revenue          AS revenue,
                       e.estimated_operational_cost AS op_cost,
                       s.amortized_overhead_per_trip AS overhead,
                       s.effective_profit           AS effective_profit
                  FROM trip_scale_snapshots s
                  JOIN trip_economics_snapshots e
                       ON  e.transform_run_id = s.source_snapshot_run_id
                       AND e.trip_id          = s.trip_id
                  JOIN trips t ON t.trip_id = s.trip_id
                 WHERE e.domain_name IS NOT NULL
            ),
            agg AS (
                SELECT scenario_name, domain_name, scale_model_name,
                       MAX(created_at)               AS last_computed_at,
                       AVG(revenue)                  AS avg_revenue,
                       AVG(op_cost)                  AS avg_op_cost,
                       AVG(overhead)                 AS avg_overhead,
                       AVG(effective_profit)         AS avg_effective_profit,
                       SUM(CASE WHEN effective_profit > 0 THEN 1 ELSE 0 END)
                                                     AS trips_break_even,
                       COUNT(*)                      AS trip_count
                  FROM joined
                 GROUP BY scenario_name, domain_name, scale_model_name
            )
            SELECT scenario_name, domain_name, scale_model_name,
                   last_computed_at, avg_revenue, avg_op_cost,
                   avg_overhead, avg_effective_profit,
                   trips_break_even, trip_count
              FROM agg
             ORDER BY scenario_name ASC, domain_name ASC, scale_model_name ASC
            """
        ).fetchall()
    finally:
        conn.close()

    cells = [
        {
            "scenario_name":        r[0],
            "domain_name":          r[1],
            "scale_model_name":     r[2],
            "last_computed_at":     r[3],
            "avg_revenue":          round(float(r[4] or 0), 2),
            "avg_operational_cost": round(float(r[5] or 0), 2),
            "avg_overhead":         round(float(r[6] or 0), 2),
            "avg_effective_profit": round(float(r[7] or 0), 2),
            "break_even_rate":      round(
                float(r[8] or 0) / float(r[9] or 1), 3
            ),
            "trip_count":           int(r[9] or 0),
        }
        for r in rows
    ]

    # Best/worst by avg_effective_profit (UI highlights these).
    best  = max(cells, key=lambda c: c["avg_effective_profit"]) if cells else None
    worst = min(cells, key=lambda c: c["avg_effective_profit"]) if cells else None

    return {
        "domains":      list_domains(),
        "scale_models": list_scale_models(),
        "cells":        cells,
        "best_cell":    best,
        "worst_cell":   worst,
    }


# ── Phase 27: volume sensitivity ────────────────────────────────────────────

@router.get("/volume-sensitivity")
def volume_sensitivity_endpoint(
    capacity_model:         str           = "pilot_capacity",
    source_snapshot_run_id: Optional[str] = None,
    domains:                Optional[str] = None,
    db: str = Depends(require_db),
) -> dict:
    """Capacity-coupled volume sweep (Phase 28).

    Given a :class:`CapacityModel` template, derive required fleet
    capacity from each sweep point's ``deliveries_per_day`` and return
    the resulting per-domain effective-profit curve.  Read-only — the
    underlying ``core.volume_sensitivity`` module does not write to any
    table.

    **Breaking change from Phase 27**: the ``scale_model=`` query param
    is removed.  The endpoint now accepts ``capacity_model=`` only.  The
    Phase 27 fixed-overhead sensitivity remains available in-process
    as ``core.volume_sensitivity.legacy_fixed_overhead_sensitivity``
    for chart-artifact compatibility, but is not routed.

    Query params:
        capacity_model:         capacity / cost-structure template
                                (default ``pilot_capacity``).
        source_snapshot_run_id: pin to one economics transform_run_id.
                                Omit for "most recent per (trip, domain)".
        domains:                comma-separated allow-list of delivery
                                domains; omit for "all domains found".
    """
    from core.volume_sensitivity import (
        sensitivity_metadata, volume_sensitivity,
    )

    domain_list = (
        [d.strip() for d in domains.split(",") if d.strip()]
        if domains else None
    )
    rows = volume_sensitivity(
        db,
        source_snapshot_run_id = source_snapshot_run_id,
        capacity_model         = capacity_model,
        delivery_domains       = domain_list,
    )
    md = sensitivity_metadata(capacity_model)

    best  = max(rows, key=lambda r: r["avg_effective_profit"]) if rows else None
    worst = min(rows, key=lambda r: r["avg_effective_profit"]) if rows else None
    domains_seen = sorted({r["delivery_domain"] for r in rows})

    return {
        "rows":                  rows,
        "capacity_model":        md["capacity_model_name"],
        "capacity_assumptions":  {
            k: v for k, v in md.items()
            if k not in ("capacity_model_name", "sweep_points", "registry_version")
        },
        "sweep_points":          md["sweep_points"],
        "registry_version":      md["registry_version"],
        "domains":               domains_seen,
        "best_row":              best,
        "worst_row":             worst,
    }


# ── Phase 33: multi-domain service mixes ────────────────────────────────────

@router.get("/service-mixes")
def service_mixes_endpoint(
    capacity_model: Optional[str] = None,
    service_mix:    Optional[str] = None,
    db: str = Depends(require_db),
) -> dict:
    """Weighted multi-domain service-mix viability across the volume sweep.

    Read-only analytical overlay (split-volume model — see
    ``core/service_mix_analysis.py``).  ``service_mix`` is an optional
    comma-separated allow-list; ``capacity_model`` optionally overrides
    the default.
    """
    from core.service_mix_analysis import compute_service_mix_summary
    from core.service_mixes        import iter_service_mixes
    from core.volume_sensitivity   import DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY
    from core.capacity_models      import list_capacity_models

    mix_filter = (
        [m.strip() for m in service_mix.split(",") if m.strip()]
        if service_mix else None
    )
    caps = [capacity_model] if capacity_model else None
    rows = compute_service_mix_summary(
        db,
        service_mix_names    = mix_filter,
        capacity_model_names = caps,
    )
    return {
        "rows":                  rows,
        "service_mixes":         [m.to_dict() for m in iter_service_mixes()],
        "capacity_models":       list_capacity_models(),
        "default_capacity_model": DEFAULT_CAPACITY_MODEL_FOR_SENSITIVITY,
        "chart":                 "service_mix_profit_by_volume.png",
        "caveats": [
            "Service mixes are weighted analytical portfolios over existing "
            "delivery domains — not new simulated event streams.",
            "Split-volume model: each component is served at total_volume × "
            "weight, keeping it within its addressable-demand ceiling; "
            "capacity overhead is shared across the whole mix.",
            "break_even_rate is a weight-weighted mean of component "
            "break-even rates — an approximation for a blended portfolio.",
        ],
    }


# ── Phase 32a: two-parameter capacity explorer ──────────────────────────────

@router.post("/parameter-grid")
def parameter_grid_endpoint(
    body: dict = Body(...),
    db: str = Depends(require_db),
) -> dict:
    """Two-parameter viability heatmap for a fixed (base_capacity, domain).

    Read-side and ephemeral — sweeps two CapacityModel parameters across
    a value grid using multi-override synthetic names, returns the
    viability margin per cell.  No snapshots written, no experiment
    recorded.

    Request body::

        {
            "base_capacity": "pilot_capacity",
            "domain":        "retail_package",
            "param_x":       "operator_to_drone_ratio",
            "values_x":      [0.6, 0.4, 0.2],
            "param_y":       "deliveries_per_drone_per_day",
            "values_y":      [8, 16, 24]
        }
    """
    from core.portfolio_summary import compute_parameter_grid

    required = ("base_capacity", "domain", "param_x", "values_x",
                "param_y", "values_y")
    if any(not body.get(k) for k in required):
        raise HTTPException(
            status_code=422,
            detail=f"parameter-grid requires non-empty: {', '.join(required)}",
        )
    try:
        return compute_parameter_grid(
            db,
            base_capacity = body["base_capacity"],
            domain        = body["domain"],
            param_x       = body["param_x"],
            values_x      = list(body["values_x"]),
            param_y       = body["param_y"],
            values_y      = list(body["values_y"]),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Phase 29 rev: viability cross-tabulation ────────────────────────────────

@router.get("/viability-summary")
def viability_summary_endpoint(
    domains: Optional[str] = None,
    db: str = Depends(require_db),
) -> dict:
    """3×4 viability grid: every (capacity_model × delivery_domain) cell
    summarised as viable / beyond addressable demand / never.

    Read-only — aggregates what ``/analytics/volume-sensitivity`` would
    already return per capacity model.

    Query params:
        domains:  comma-separated allow-list; omit for all.
    """
    from core.capacity_models   import list_capacity_models
    from core.delivery_domains  import list_domains
    from core.portfolio_summary import aggregate_pain_points, diagnose_viability_cells
    from core.volume_sensitivity import compute_viability_summary, viability_state

    domain_list = (
        [d.strip() for d in domains.split(",") if d.strip()]
        if domains else None
    )

    cells = compute_viability_summary(db, delivery_domains=domain_list)
    # Attach the state label here so the frontend doesn't reimplement it.
    for c in cells:
        c["state"] = viability_state(c)

    # Pain-points diagnostics — answers *why* each non-viable cell fails.
    # Note: diagnose_viability_cells runs across all registered domains
    # regardless of the `domains` filter so the dominant-constraint
    # attribution is computed on the full grid; if a domain allow-list
    # was provided we filter the diagnostics post-hoc.
    diagnostics = diagnose_viability_cells(db)
    if domain_list:
        diagnostics = [
            d for d in diagnostics if d["delivery_domain"] in domain_list
        ]
    pain_points = aggregate_pain_points(diagnostics)

    # Continuous viability margin — pulled from the diagnostics' anchor
    # gap (dollars per delivery, signed).  Attached per cell so the
    # frontend ViabilityGrid can colour cells along a diverging scale
    # rather than the categorical green/yellow/red.
    margin_by_cell = {
        (d["capacity_model"], d["delivery_domain"]): d.get("gap_at_anchor")
        for d in diagnostics
    }
    for c in cells:
        m = margin_by_cell.get((c["capacity_model"], c["delivery_domain"]))
        c["viability_margin"] = m
    margins = [m for m in margin_by_cell.values() if m is not None]
    max_abs = max((abs(m) for m in margins), default=0.0)

    # Phase 31: the domain axis is the union of the registry and what's
    # actually in the cells — synthetic parameter-sweep variants
    # (``base@field=value``) live only in snapshot data, never in the
    # registry, and must still appear as grid columns.
    domains_axis = sorted(
        set(list_domains()) | {c["delivery_domain"] for c in cells}
    )
    # Phase 32: capacity axis = registry ∪ synthetic capacities present
    # in the cells (sourced from what-if experiment definitions).
    # Registered capacities keep their canonical order; synthetics append.
    registered_caps = list_capacity_models()
    synthetic_caps = sorted(
        {c["capacity_model"] for c in cells} - set(registered_caps)
    )
    capacity_axis = registered_caps + synthetic_caps

    return {
        "cells":                      cells,
        "capacity_models":            capacity_axis,
        "delivery_domains":           domains_axis,
        "pain_points":                pain_points,
        "viability_margin_max_abs":   max_abs,
    }


@router.get("/telemetry-health")
def telemetry_health_endpoint(db: str = Depends(require_db)) -> dict:
    """Anomaly counts + drone-level health (Phase 21)."""
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        # Anomaly counts straight from the raw observations.
        anomalies = conn.execute(
            """
            SELECT de.scenario_name,
                   SUM(CASE WHEN t.battery_temp_c > 50 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN t.motor_temp_c   > 85 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN t.signal_strength_pct < 60 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN t.gps_signal_quality  < 60 THEN 1 ELSE 0 END)
              FROM delivery_events de
              JOIN telemetry_observations t ON t.event_id = de.event_id
             WHERE de.scenario_name IS NOT NULL
             GROUP BY de.scenario_name
             ORDER BY de.scenario_name ASC
            """
        ).fetchall()
        obstacles = dict(conn.execute(
            "SELECT scenario_name, COUNT(*) FROM delivery_events "
            " WHERE event_type = 'obstacle_warning' AND scenario_name IS NOT NULL "
            " GROUP BY scenario_name"
        ).fetchall())
        drones = conn.execute(
            "SELECT drone_id, battery_cycle_count, battery_health_pct, status "
            "  FROM drones ORDER BY drone_id ASC"
        ).fetchall()
    finally:
        conn.close()
    return {
        "anomalies_by_scenario": [
            {
                "scenario_name":         row[0],
                "battery_hot_count":     int(row[1] or 0),
                "motor_hot_count":       int(row[2] or 0),
                "signal_weak_count":     int(row[3] or 0),
                "gps_degraded_count":    int(row[4] or 0),
                "obstacle_warning_count": int(obstacles.get(row[0], 0)),
            }
            for row in anomalies
        ],
        "drone_health": [
            {
                "drone_id":            d[0],
                "battery_cycle_count": int(d[1] or 0),
                "battery_health_pct":  round(float(d[2] or 0.0), 2),
                "status":              d[3],
            }
            for d in drones
        ],
    }
