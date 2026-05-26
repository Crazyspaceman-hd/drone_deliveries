"""
transforms/economics.py

Re-computable trip economics derivation.

Before Phase 20 these numbers were written by the simulator at trip-end.
After Phase 20 they are derived here from raw event/leg/trip data —
which means changing an economic assumption can be replayed without
regenerating events.

Reads:
    * trips        — trip_id, scenario_name, status, run_id
    * trip_legs    — start/end coordinates per leg (distance facts)
    * delivery_events — maintenance_required + emergency_return events
                      attributed to a trip via event.trip_id

Writes (UPDATE on trips):
    trip_distance_km
    estimated_energy_cost
    estimated_maintenance_cost
    estimated_operational_cost
    estimated_revenue
    estimated_profit
    emergency_return_penalty_applied

Lineage:
    Inserts one row into ``transformation_runs`` per ``run()`` call.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Optional

from core.delivery_domains import (
    DELIVERY_DOMAIN_REGISTRY_VERSION, DeliveryDomain, get_domain,
)
from core.economic_models import EconomicModel, from_scenario_name, to_parameters_json
from transforms.runs import record_transform_run


TRANSFORM_NAME    = "economics"
TRANSFORM_VERSION = "economics.v2"   # Phase 22: accepts delivery_domain overlay
RUN_ORDER         = 10               # economics first — hybrid reads trip_distance_km from it


# ── Domain → revenue uplift formula (Phase 22) ──────────────────────────────
# Per-trip revenue under a domain is the EconomicModel's base fee plus two
# additive demand-side terms:
#
#   revenue = delivery_fee
#           + delivery_fee * premium_share * PREMIUM_UPLIFT_PCT
#           + average_order_value_usd       * AOV_SHARE
#
# So a domain with high premium_share and high AOV earns more per delivery
# than a low-premium / low-AOV domain on the SAME trip.  All other terms
# in the cost model (energy, maintenance, labour, depreciation, penalty)
# are *physics-side* and stay invariant under domain change.
PREMIUM_UPLIFT_PCT = 0.50   # premium orders surcharge 50% of the base fee
AOV_SHARE          = 0.05   # the delivery captures 5% of total order value


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371.0088
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _trip_distance_km(legs: list[tuple]) -> float:
    """Sum haversine across legs.  legs = [(start_lat, start_lon, end_lat, end_lon), ...]"""
    total = 0.0
    for (s_lat, s_lon, e_lat, e_lon) in legs:
        if None in (s_lat, s_lon, e_lat, e_lon):
            continue
        total += _haversine_km((s_lat, s_lon), (e_lat, e_lon))
    return round(total, 4)


def _compute_for_trip(
    *, distance_km: float, maintenance_events: int, aborted: bool,
    model: EconomicModel, domain: DeliveryDomain,
) -> dict:
    """Per-trip economics under a (model, domain) pair.

    Physics-side fields (energy, maintenance, operational cost, distance,
    penalty) are computed from model + trip facts ONLY.  Domain influences
    revenue and therefore profit; nothing else.  This invariant is
    enforced by ``tests/test_delivery_domains.py``.
    """
    # ── physics side: domain MUST NOT appear in any of these lines ──────
    energy_cost = distance_km * model.avg_kwh_per_km * model.energy_cost_per_kwh
    maint_cost  = maintenance_events * model.maintenance_cost_per_event
    penalty     = model.emergency_return_penalty if aborted else 0.0
    op_cost     = (energy_cost + maint_cost + model.labor_cost_per_delivery
                   + model.drone_depreciation_per_trip + penalty)

    # ── demand side: revenue is the only domain-influenced quantity ─────
    if aborted:
        revenue = 0.0
    else:
        premium_uplift = (model.delivery_fee
                          * domain.premium_share * PREMIUM_UPLIFT_PCT)
        aov_uplift     = domain.average_order_value_usd * AOV_SHARE
        revenue        = model.delivery_fee + premium_uplift + aov_uplift

    profit = revenue - op_cost
    return {
        "trip_distance_km":                  round(distance_km, 4),
        "estimated_energy_cost":             round(energy_cost,  4),
        "estimated_maintenance_cost":        round(maint_cost,   4),
        "estimated_operational_cost":        round(op_cost,      4),
        "estimated_revenue":                 round(revenue,      4),
        "estimated_profit":                  round(profit,       4),
        "emergency_return_penalty_applied":  round(penalty,      4),
    }


def run(
    db_path: str,
    *,
    run_id:            Optional[str]            = None,
    model:             Optional[EconomicModel]  = None,
    delivery_domain:   Optional[DeliveryDomain | str] = None,
    experiment_run_id: Optional[str]            = None,
) -> dict:
    """Compute economics for every (or one) trip and UPDATE trips.

    Args:
        db_path:         SQLite file.
        run_id:          Limit to one simulation run.  None = every trip
                         in the DB.
        model:           Override EconomicModel.  None = each trip's
                         scenario default.
        delivery_domain: Demand-side overlay (Phase 22).  Accepts a name,
                         a DeliveryDomain instance, or None for the
                         default profile.  Influences revenue + profit
                         only; never touches physics-side fields.

    Side effects:
        * UPDATE trips.estimated_* with the most-recent recompute.
        * INSERT one row per trip into trip_economics_snapshots
          (Phase 22), keyed by (trip_id, transform_run_id), carrying the
          domain_name so two recomputes coexist for comparison.
        * INSERT one row into transformation_runs with parameters_json
          describing model + domain + registry versions.
        experiment_run_id: (Phase 24) links this transform row back to
          the experiment that triggered it.  None for direct calls.
    """
    import json
    import uuid
    from datetime import datetime, timezone

    domain = get_domain(delivery_domain)
    # Pre-allocate so snapshot rows can reference it during the loop.
    transform_run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        params = ()
        where  = "WHERE 1=1"
        if run_id is not None:
            where += " AND run_id = ?"
            params = (run_id,)
        trips = conn.execute(
            f"""
            SELECT trip_id, scenario_name, status, run_id
              FROM trips
            {where}
            """,
            params,
        ).fetchall()

        cur = conn.cursor()
        rows_updated = 0
        for trip_id, scenario_name, status, t_run_id in trips:
            # Distance: sum over the trip's legs.  For aborted trips leg 3
            # was never inserted, so the sum naturally truncates.
            legs = cur.execute(
                """
                SELECT start_lat, start_lon, end_lat, end_lon
                  FROM trip_legs
                 WHERE trip_id = ?
                 ORDER BY leg_index ASC
                """,
                (trip_id,),
            ).fetchall()
            dist = _trip_distance_km(legs)

            # Maintenance events attributable to this trip.
            maint_count = cur.execute(
                """
                SELECT COUNT(*) FROM delivery_events
                 WHERE trip_id = ?
                   AND event_type IN ('maintenance_required', 'emergency_return')
                """,
                (trip_id,),
            ).fetchone()[0]

            aborted = status == "aborted"

            scenario_model = (
                model if model is not None
                else from_scenario_name(scenario_name or "suburban_standard")
            )
            econ = _compute_for_trip(
                distance_km=dist, maintenance_events=int(maint_count),
                aborted=aborted, model=scenario_model, domain=domain,
            )

            cur.execute(
                """
                UPDATE trips
                   SET trip_distance_km                 = ?,
                       estimated_energy_cost            = ?,
                       estimated_maintenance_cost       = ?,
                       estimated_operational_cost       = ?,
                       estimated_revenue                = ?,
                       estimated_profit                 = ?,
                       emergency_return_penalty_applied = ?
                 WHERE trip_id = ?
                """,
                (
                    econ["trip_distance_km"],
                    econ["estimated_energy_cost"],
                    econ["estimated_maintenance_cost"],
                    econ["estimated_operational_cost"],
                    econ["estimated_revenue"],
                    econ["estimated_profit"],
                    econ["emergency_return_penalty_applied"],
                    trip_id,
                ),
            )
            # Phase 22: snapshot row keyed by (trip_id, transform_run_id).
            # Multiple recomputes coexist for cross-domain comparison.
            cur.execute(
                """
                INSERT OR REPLACE INTO trip_economics_snapshots (
                    trip_id, transform_run_id, domain_name,
                    trip_distance_km, estimated_energy_cost,
                    estimated_maintenance_cost, estimated_operational_cost,
                    estimated_revenue, estimated_profit,
                    emergency_return_penalty_applied, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trip_id, transform_run_id, domain.name,
                    econ["trip_distance_km"],
                    econ["estimated_energy_cost"],
                    econ["estimated_maintenance_cost"],
                    econ["estimated_operational_cost"],
                    econ["estimated_revenue"],
                    econ["estimated_profit"],
                    econ["emergency_return_penalty_applied"],
                    created_at,
                ),
            )
            rows_updated += 1
        conn.commit()
    finally:
        conn.close()

    # Phase 22: parameters_json now captures model + domain + registry
    # versions so an analyst can correlate snapshots back to the inputs
    # that produced them.
    params_json = json.dumps(
        {
            "model":             None if model is None else model.name,
            "delivery_domain":   domain.name,
            "registry_versions": {
                "delivery_domain": DELIVERY_DOMAIN_REGISTRY_VERSION,
            },
        },
        separators=(",", ":"), sort_keys=True,
    )
    notes = f"domain={domain.name}"
    if model is not None:
        notes += f"; model={model.name}"
    tx_id = record_transform_run(
        db_path,
        source_run_id     = run_id,
        transform_name    = TRANSFORM_NAME,
        transform_version = TRANSFORM_VERSION,
        parameters_json   = params_json,
        row_count         = rows_updated,
        notes             = notes,
        transform_run_id  = transform_run_id,    # pre-allocated above
        experiment_run_id = experiment_run_id,   # Phase 24: FK to experiment_runs
    )
    return {
        "transform_run_id":  tx_id,
        "transform_name":    TRANSFORM_NAME,
        "transform_version": TRANSFORM_VERSION,
        "source_run_id":     run_id,
        "rows_updated":      rows_updated,
        "model_override":    None if model is None else model.name,
        "delivery_domain":   domain.name,
    }
