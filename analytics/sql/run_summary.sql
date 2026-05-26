-- run_summary.sql
-- One row per simulation_runs entry, joined to per-run operational and
-- economic aggregates.  Use this to compare runs side-by-side.

WITH trip_stats AS (
    SELECT run_id,
           COUNT(*)                                              AS trips,
           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)   AS completed_trips,
           SUM(CASE WHEN status='aborted'   THEN 1 ELSE 0 END)   AS aborted_trips,
           SUM(estimated_revenue)                                AS total_revenue,
           SUM(estimated_profit)                                 AS total_profit,
           AVG(estimated_profit)                                 AS avg_profit_per_trip
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
)
SELECT r.run_id,
       SUBSTR(r.created_at, 1, 19)            AS created_at,
       r.scenario_names                       AS scenarios,
       r.seed                                 AS seed,
       r.simulator_version                    AS simulator_version,
       r.assumption_version                   AS assumption_version,
       r.git_commit                           AS git_commit,
       COALESCE(t.trips,           0)         AS trips,
       COALESCE(t.completed_trips, 0)         AS completed_trips,
       COALESCE(t.aborted_trips,   0)         AS aborted_trips,
       ROUND(100.0 * t.completed_trips / NULLIF(t.trips, 0), 2)
                                              AS completion_rate_pct,
       ROUND(t.total_revenue,        2)       AS total_revenue,
       ROUND(t.total_profit,         2)       AS total_profit,
       ROUND(t.avg_profit_per_trip,  2)       AS avg_profit_per_trip,
       ROUND(1.0 * COALESCE(e.emergencies,  0) / NULLIF(t.trips, 0), 4)
                                              AS emergency_return_rate,
       ROUND(1.0 * COALESCE(e.maintenances, 0) / NULLIF(t.trips, 0), 4)
                                              AS maintenance_rate
  FROM simulation_runs r
  LEFT JOIN trip_stats  t ON t.run_id = r.run_id
  LEFT JOIN event_stats e ON e.run_id = r.run_id
 ORDER BY r.created_at DESC, r.run_id DESC;
