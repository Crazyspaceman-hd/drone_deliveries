-- feasibility_rankings.sql (DuckDB / Parquet)
-- Run-level feasibility ranking using the same weighted formula as the
-- Python BI layer:
--
--   score = 50 * completion_rate
--         + 30 * clip(profit_margin_pct / 100, -1..+1)
--         - 40 * emergency_rate
--         - 10 * maintenance_per_trip
--
-- Labels mirror core/business_intelligence.py thresholds (25, 10).
--
-- This file is a portable, run-by-run version of the Python scoring — it
-- gives an analyst the same answer straight from Parquet without going
-- back through SQLite.

WITH trip_stats AS (
    SELECT run_id,
           COUNT(*)                                              AS trips,
           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)   AS completed,
           SUM(estimated_revenue)                                AS revenue,
           SUM(estimated_profit)                                 AS profit,
           AVG(estimated_profit)                                 AS avg_profit
      FROM trips
     WHERE run_id IS NOT NULL
     GROUP BY run_id
),
event_stats AS (
    SELECT run_id,
           SUM(CASE WHEN event_type='emergency_return'     THEN 1 ELSE 0 END) AS emergencies,
           SUM(CASE WHEN event_type='maintenance_required' THEN 1 ELSE 0 END) AS maintenances
      FROM delivery_events
     WHERE run_id IS NOT NULL
     GROUP BY run_id
),
metrics AS (
    SELECT r.run_id,
           r.scenario_names                                          AS scenario,
           1.0 * t.completed / NULLIF(t.trips, 0)                    AS completion_rate,
           1.0 * COALESCE(e.emergencies, 0) / NULLIF(t.trips, 0)     AS emergency_rate,
           1.0 * COALESCE(e.maintenances, 0) / NULLIF(t.trips, 0)    AS maintenance_per_trip,
           CASE WHEN t.revenue > 0
                THEN 100.0 * t.profit / t.revenue
                ELSE NULL
           END                                                       AS profit_margin_pct,
           t.profit                                                  AS total_profit,
           t.avg_profit                                              AS avg_profit
      FROM simulation_runs r
      LEFT JOIN trip_stats  t ON t.run_id = r.run_id
      LEFT JOIN event_stats e ON e.run_id = r.run_id
),
scored AS (
    SELECT *,
           50.0 * COALESCE(completion_rate, 0)
         + 30.0 * COALESCE(GREATEST(LEAST(profit_margin_pct / 100.0, 1.0), -1.0), 0)
         - 40.0 * COALESCE(emergency_rate, 0)
         - 10.0 * COALESCE(maintenance_per_trip, 0)
             AS feasibility_score
      FROM metrics
)
SELECT run_id,
       scenario,
       ROUND(feasibility_score, 2)              AS feasibility_score,
       CASE
         WHEN feasibility_score >= 25 THEN 'strong_candidate'
         WHEN feasibility_score >= 10 THEN 'borderline'
         ELSE 'poor_candidate'
       END                                       AS feasibility_label,
       ROUND(completion_rate, 4)                AS completion_rate,
       ROUND(emergency_rate, 4)                 AS emergency_rate,
       ROUND(maintenance_per_trip, 4)           AS maintenance_per_trip,
       ROUND(profit_margin_pct, 2)              AS profit_margin_pct,
       ROUND(total_profit, 2)                   AS total_profit
  FROM scored
 ORDER BY feasibility_score DESC;
