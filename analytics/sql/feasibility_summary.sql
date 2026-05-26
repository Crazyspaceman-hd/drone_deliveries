-- feasibility_summary.sql
-- Per-scenario operational + economic inputs used by the BI scoring layer
-- (see core/business_intelligence.py).  Scoring itself happens in Python so
-- the weights and thresholds stay in one auditable place.

WITH trip_stats AS (
    SELECT scenario_name,
           COUNT(*)                                              AS trips,
           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)   AS completed_trips,
           SUM(CASE WHEN status='aborted'   THEN 1 ELSE 0 END)   AS aborted_trips,
           SUM(estimated_revenue)                                AS total_revenue,
           SUM(estimated_operational_cost)                       AS total_operational_cost,
           SUM(estimated_profit)                                 AS total_profit,
           AVG(estimated_profit)                                 AS avg_profit_per_trip
      FROM trips
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
),
event_counts AS (
    SELECT scenario_name,
           SUM(CASE WHEN event_type='emergency_return'     THEN 1 ELSE 0 END) AS emergencies,
           SUM(CASE WHEN event_type='maintenance_required' THEN 1 ELSE 0 END) AS maintenance_events
      FROM delivery_events
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
)
SELECT t.scenario_name,
       t.trips,
       t.completed_trips,
       t.aborted_trips,
       ROUND(100.0 * t.completed_trips / NULLIF(t.trips, 0),       2) AS completion_rate_pct,
       ROUND(t.total_revenue,                                       2) AS total_revenue,
       ROUND(t.total_operational_cost,                              2) AS total_operational_cost,
       ROUND(t.total_profit,                                        2) AS total_profit,
       ROUND(t.avg_profit_per_trip,                                 2) AS avg_profit_per_trip,
       CASE WHEN t.total_revenue > 0
            THEN ROUND(100.0 * t.total_profit / t.total_revenue,    2)
            ELSE NULL
       END                                                            AS profit_margin_pct,
       ROUND(1.0 * COALESCE(e.emergencies,        0) / NULLIF(t.trips, 0), 4) AS emergency_return_rate,
       ROUND(1.0 * COALESCE(e.maintenance_events, 0) / NULLIF(t.trips, 0), 4) AS maintenance_events_per_trip
  FROM trip_stats t
  LEFT JOIN event_counts e ON e.scenario_name = t.scenario_name
 ORDER BY t.scenario_name ASC;
