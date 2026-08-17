-- assumption_summary.sql
-- Observed outcomes per scenario.  Compare these against the configured
-- knobs in core/scenarios.py (and the narrative in docs/assumptions.md)
-- to see whether the simulator's behavior matches the assumptions you
-- thought you were dialling in.
--
-- This query intentionally does NOT recompute Python config logic — it
-- exposes raw observed values straight from the DB.

WITH trip_stats AS (
    SELECT scenario_name,
           COUNT(*)                                            AS trips,
           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_trips,
           SUM(CASE WHEN status='aborted'   THEN 1 ELSE 0 END) AS aborted_trips,
           AVG(trip_distance_km)                               AS avg_distance_km,
           AVG(estimated_profit)                               AS avg_profit_per_trip,
           AVG(estimated_operational_cost)                     AS avg_op_cost
      FROM trips
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
),
event_stats AS (
    SELECT scenario_name,
           SUM(CASE WHEN event_type='emergency_return'     THEN 1 ELSE 0 END) AS emergencies,
           SUM(CASE WHEN event_type='maintenance_required' THEN 1 ELSE 0 END) AS maintenances,
           SUM(CASE WHEN event_type='battery_warning'      THEN 1 ELSE 0 END) AS battery_warnings,
           SUM(CASE WHEN event_type='route_deviation'      THEN 1 ELSE 0 END) AS route_deviations
      FROM delivery_events
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
)
SELECT t.scenario_name,
       t.trips,
       ROUND(100.0 * t.completed_trips / NULLIF(t.trips, 0),  2) AS completion_rate_pct,
       ROUND(t.avg_distance_km,                                3) AS observed_avg_distance_km,
       ROUND(t.avg_op_cost,                                    2) AS observed_avg_op_cost,
       ROUND(t.avg_profit_per_trip,                            2) AS observed_avg_profit_per_trip,
       ROUND(1.0 * COALESCE(e.emergencies,  0)    / NULLIF(t.trips, 0), 4) AS observed_emergency_rate,
       ROUND(1.0 * COALESCE(e.maintenances, 0)    / NULLIF(t.trips, 0), 4) AS observed_maintenance_rate,
       ROUND(1.0 * COALESCE(e.battery_warnings,0) / NULLIF(t.trips, 0), 4) AS observed_battery_warning_rate,
       ROUND(1.0 * COALESCE(e.route_deviations,0) / NULLIF(t.trips, 0), 4) AS observed_route_deviation_rate
  FROM trip_stats t
  LEFT JOIN event_stats e ON e.scenario_name = t.scenario_name
 ORDER BY t.scenario_name ASC;
