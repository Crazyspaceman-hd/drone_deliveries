"""GET /analytics/delivery-displacement — the headline business endpoint."""

from fastapi import APIRouter, Depends

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
