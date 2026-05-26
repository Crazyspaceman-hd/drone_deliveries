"""
transforms/hybrid.py

Re-computable hybrid fulfillment decisions.

Before Phase 20 the simulator called ``decide_fulfillment`` at order-write
time and persisted the result.  After Phase 20 the simulator writes the
order's *intrinsic* characteristics (payload, urgency, premium,
congestion, queue pressure) and this transform computes the *decision*
fields from them.

Reads:
    * orders  — characteristics + trip_id
    * trips   — trip_distance_km (set by the economics transform)
    * trip_legs — fallback distance if the economics transform hasn't run yet

Writes (UPDATE on orders):
    fulfillment_mode
    activation_reason
    truck_baseline_cost
    truck_baseline_latency_min
    drone_estimated_latency_min

Lineage:
    Inserts one row into ``transformation_runs`` per ``run()`` call.

The activation thresholds live as a frozen dataclass so they can be
overridden per call — that's what unlocks sensitivity analysis without
re-running the simulator.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from typing import Optional

from core.hybrid import (
    DRONE, HEAVY_PAYLOAD_KG, HIGH_CONGESTION, HIGH_QUEUE_PRESSURE,
    HYBRID, LIGHT_PAYLOAD_KG, SHORT_DISTANCE_KM, TRUCK,
    DRONE_CRUISE_KMH, DRONE_PREP_MIN,
    TRUCK_BASE_COST_PER_DELIVERY, TRUCK_BASE_LATENCY_MIN,
    TRUCK_BATCH_LATENCY_PER_STOP, TRUCK_BATCH_SIZE,
    TRUCK_CONGESTION_COST_PENALTY, TRUCK_CONGESTION_LATENCY_MULT,
    OrderCharacteristics, decide_fulfillment,
    estimate_drone_latency_min, estimate_truck_cost,
    estimate_truck_latency_min,
)
from transforms.runs import record_transform_run

TRANSFORM_NAME    = "hybrid"
TRANSFORM_VERSION = "hybrid.v1"
RUN_ORDER         = 20   # depends on economics having set trip_distance_km


@dataclass(frozen=True)
class HybridThresholds:
    """Tunable activation thresholds.  Defaults mirror core.hybrid constants."""
    light_payload_kg:        float = LIGHT_PAYLOAD_KG
    heavy_payload_kg:        float = HEAVY_PAYLOAD_KG
    short_distance_km:       float = SHORT_DISTANCE_KM
    high_congestion:         float = HIGH_CONGESTION
    high_queue_pressure:     float = HIGH_QUEUE_PRESSURE
    truck_batch_size:        int   = TRUCK_BATCH_SIZE


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371.0088
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _resolve_distance_km(cur: sqlite3.Cursor, trip_id: Optional[str]) -> float:
    """Prefer the economics-transform's trip_distance_km; otherwise sum legs."""
    if trip_id is None:
        return 0.0
    row = cur.execute(
        "SELECT trip_distance_km FROM trips WHERE trip_id = ?", (trip_id,),
    ).fetchone()
    if row and row[0] is not None:
        return float(row[0])
    legs = cur.execute(
        """
        SELECT start_lat, start_lon, end_lat, end_lon
          FROM trip_legs WHERE trip_id = ? ORDER BY leg_index ASC
        """,
        (trip_id,),
    ).fetchall()
    total = 0.0
    for s_lat, s_lon, e_lat, e_lon in legs:
        if None not in (s_lat, s_lon, e_lat, e_lon):
            total += _haversine_km((s_lat, s_lon), (e_lat, e_lon))
    return total


def run(
    db_path: str,
    *,
    run_id:     Optional[str] = None,
    thresholds: Optional[HybridThresholds] = None,
) -> dict:
    """Compute hybrid fulfillment decisions for every (or one) order."""
    th = thresholds or HybridThresholds()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        where_clause = "WHERE payload_weight_kg IS NOT NULL"
        params: tuple = ()
        if run_id is not None:
            where_clause += " AND run_id = ?"
            params = (run_id,)
        orders = cur.execute(
            f"""
            SELECT order_id, trip_id,
                   payload_weight_kg, urgency_level, estimated_prep_time_min,
                   promised_delivery_window_min, premium_delivery,
                   congestion_factor, queue_pressure
              FROM orders
            {where_clause}
            """,
            params,
        ).fetchall()

        rows_updated = 0
        for (order_id, trip_id, payload, urgency, prep, window, premium,
             cong, queue) in orders:
            chars = OrderCharacteristics(
                payload_weight_kg            = float(payload),
                urgency_level                = urgency,
                estimated_prep_time_min      = float(prep   or 0.0),
                promised_delivery_window_min = float(window or 0.0),
                premium_delivery             = bool(premium),
                congestion_factor            = float(cong   or 0.0),
                queue_pressure               = float(queue  or 0.0),
            )
            distance_km = _resolve_distance_km(cur, trip_id)
            mode, reason = _decide_with_thresholds(chars, distance_km, th)
            truck_cost    = estimate_truck_cost(chars, distance_km,
                                                batch_size=th.truck_batch_size)
            truck_latency = estimate_truck_latency_min(chars, distance_km,
                                                       batch_size=th.truck_batch_size)
            drone_latency = estimate_drone_latency_min(chars, distance_km)

            cur.execute(
                """
                UPDATE orders
                   SET fulfillment_mode            = ?,
                       activation_reason           = ?,
                       truck_baseline_cost         = ?,
                       truck_baseline_latency_min  = ?,
                       drone_estimated_latency_min = ?
                 WHERE order_id = ?
                """,
                (mode, reason, truck_cost, truck_latency, drone_latency, order_id),
            )
            rows_updated += 1
        conn.commit()
    finally:
        conn.close()

    tx_id = record_transform_run(
        db_path,
        source_run_id     = run_id,
        transform_name    = TRANSFORM_NAME,
        transform_version = TRANSFORM_VERSION,
        parameters_json   = (None if thresholds is None
                             else json.dumps(asdict(th), sort_keys=True)),
        row_count         = rows_updated,
        notes             = (None if thresholds is None
                             else "override thresholds"),
    )
    return {
        "transform_run_id":   tx_id,
        "transform_name":     TRANSFORM_NAME,
        "transform_version":  TRANSFORM_VERSION,
        "source_run_id":      run_id,
        "rows_updated":       rows_updated,
        "thresholds_override": thresholds is not None,
    }


def _decide_with_thresholds(
    chars: OrderCharacteristics, distance_km: float, th: HybridThresholds,
) -> tuple[str, str]:
    """Same algorithm as core.hybrid.decide_fulfillment but parameterised."""
    if chars.payload_weight_kg > th.heavy_payload_kg:
        return TRUCK, "heavy_payload"
    reasons: list[str] = []
    if chars.premium_delivery:                       reasons.append("premium")
    if chars.urgency_level == "high":                reasons.append("urgent")
    if chars.payload_weight_kg < th.light_payload_kg: reasons.append("light_payload")
    if chars.congestion_factor > th.high_congestion:  reasons.append("congestion_bypass")
    if chars.queue_pressure   > th.high_queue_pressure: reasons.append("queue_pressure")
    if distance_km < th.short_distance_km:           reasons.append("short_distance")

    if len(reasons) >= 3:
        return DRONE, ",".join(reasons)
    if len(reasons) == 2:
        return HYBRID, ",".join(reasons)
    if reasons:
        return TRUCK, "default_baseline_with_signal:" + ",".join(reasons)
    return TRUCK, "default_baseline"
