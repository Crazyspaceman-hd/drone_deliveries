"""
core/displacement.py

Synthetic estimate of how many traditional truck deliveries the drone
fleet hypothetically displaced, plus a rough cost comparison.

Assumptions (intentionally simple and visible)
─────────────────────────────────────────────
- Each ``returned_to_depot`` event = one fulfilled drone delivery.
  Aborted trips (no return event) do not displace anything.
- One drone delivery displaces exactly one truck delivery.
- Truck cost per delivery is a flat configurable constant.  Public
  reporting on last-mile truck cost varies widely; the default here is
  a placeholder.
- Drone operational cost comes from ``trips.estimated_operational_cost``,
  which was populated by the simulator in Phase 10.

Cost difference = truck_cost − drone_cost.  Positive = savings, negative
= drone delivery costs more than the truck baseline.

Displacement percentage is 1:1 here (100% of completed drone deliveries
are assumed to have displaced a truck delivery); kept as a returned
field so a smarter model later can vary it.
"""

from __future__ import annotations

import sqlite3
from typing import Any


# Placeholder default — picked to land in a plausible "delivery van + driver
# allocated cost" ballpark.  Not a calibrated estimate.
DEFAULT_TRUCK_COST_PER_DELIVERY = 12.0


def _round(v: float, n: int = 2) -> float:
    return round(float(v), n)


def compute_delivery_displacement(
    db_path: str,
    truck_cost_per_delivery: float = DEFAULT_TRUCK_COST_PER_DELIVERY,
) -> dict[str, Any]:
    """Per-scenario + totals.

    Returns ``{"truck_cost_per_delivery": ..., "by_scenario": [...],
              "totals": {...}}``.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            WITH delivered AS (
                SELECT scenario_name,
                       COUNT(*) AS completed_drone_deliveries
                  FROM delivery_events
                 WHERE event_type = 'returned_to_depot'
                   AND scenario_name IS NOT NULL
                 GROUP BY scenario_name
            ),
            costs AS (
                SELECT scenario_name,
                       SUM(estimated_operational_cost) AS drone_op_cost
                  FROM trips
                 WHERE status = 'completed'
                   AND scenario_name IS NOT NULL
                 GROUP BY scenario_name
            )
            SELECT d.scenario_name,
                   d.completed_drone_deliveries,
                   COALESCE(c.drone_op_cost, 0.0) AS drone_op_cost
              FROM delivered d
              LEFT JOIN costs c ON c.scenario_name = d.scenario_name
             ORDER BY d.scenario_name ASC
            """
        ).fetchall()
    finally:
        conn.close()

    by_scenario: list[dict] = []
    total_deliveries = 0
    total_truck_cost = 0.0
    total_drone_cost = 0.0
    for scenario_name, deliveries, drone_cost in rows:
        truck_cost = float(deliveries) * truck_cost_per_delivery
        drone_cost = float(drone_cost or 0.0)
        diff       = truck_cost - drone_cost
        by_scenario.append({
            "scenario_name":                    scenario_name,
            "completed_drone_deliveries":       int(deliveries),
            "estimated_displacement_pct":       100.0,  # 1:1 by assumption
            "estimated_truck_delivery_cost":    _round(truck_cost),
            "estimated_drone_operational_cost": _round(drone_cost),
            "estimated_cost_difference":        _round(diff),
        })
        total_deliveries += int(deliveries)
        total_truck_cost += truck_cost
        total_drone_cost += drone_cost

    totals = {
        "completed_drone_deliveries":       total_deliveries,
        "estimated_displacement_pct":       100.0,
        "estimated_truck_delivery_cost":    _round(total_truck_cost),
        "estimated_drone_operational_cost": _round(total_drone_cost),
        "estimated_cost_difference":        _round(total_truck_cost - total_drone_cost),
    }
    return {
        "truck_cost_per_delivery": truck_cost_per_delivery,
        "by_scenario":             by_scenario,
        "totals":                  totals,
    }
