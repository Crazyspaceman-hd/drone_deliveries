-- scenario_economics.sql
-- Per-scenario synthetic profit/cost summary.
--
-- Numbers come from the trip economics fields populated by the simulator
-- (see core/simulator.py _compute_economics).  They are illustrative only.

WITH per_trip AS (
    SELECT scenario_name,
           status,
           trip_distance_km,
           estimated_energy_cost,
           estimated_maintenance_cost,
           estimated_operational_cost,
           estimated_revenue,
           estimated_profit,
           emergency_return_penalty_applied
      FROM trips
     WHERE scenario_name IS NOT NULL
),
emerg AS (
    SELECT scenario_name, COUNT(*) AS emergency_return_count
      FROM delivery_events
     WHERE event_type = 'emergency_return'
       AND scenario_name IS NOT NULL
     GROUP BY scenario_name
)
SELECT t.scenario_name,
       COUNT(*)                                                            AS trips,
       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)                AS completed_trips,
       SUM(CASE WHEN status = 'aborted'   THEN 1 ELSE 0 END)                AS aborted_trips,
       ROUND(SUM(estimated_revenue),                  2) AS total_revenue,
       ROUND(SUM(estimated_operational_cost),         2) AS total_operational_cost,
       ROUND(SUM(estimated_energy_cost),              2) AS total_energy_cost,
       ROUND(SUM(estimated_maintenance_cost),         2) AS total_maintenance_cost,
       ROUND(SUM(estimated_profit),                   2) AS total_profit,
       ROUND(AVG(estimated_profit),                   2) AS avg_profit_per_trip,
       ROUND(AVG(CASE WHEN status = 'completed' THEN estimated_profit ELSE NULL END), 2)
                                                          AS avg_profit_per_completed_trip,
       CASE
         WHEN SUM(estimated_revenue) > 0
           THEN ROUND(100.0 * SUM(estimated_profit) / SUM(estimated_revenue), 1)
         ELSE NULL
       END                                                AS profit_margin_pct,
       COALESCE(e.emergency_return_count, 0)              AS emergency_return_count
  FROM per_trip t
  LEFT JOIN emerg e ON e.scenario_name = t.scenario_name
 GROUP BY t.scenario_name
 ORDER BY total_profit DESC;
