-- maintenance_burden.sql (DuckDB / Parquet)
-- Maintenance events per trip per run/scenario.  Splits scheduled vs
-- emergency-return-triggered maintenance so the operational story is
-- visible without joining back to event payloads.

WITH trip_counts AS (
    SELECT run_id, COUNT(*) AS trips
      FROM trips
     WHERE run_id IS NOT NULL
     GROUP BY run_id
),
maint AS (
    SELECT run_id,
           SUM(CASE WHEN event_type='maintenance_required'  THEN 1 ELSE 0 END) AS maint_required,
           SUM(CASE WHEN event_type='maintenance_completed' THEN 1 ELSE 0 END) AS maint_completed,
           SUM(CASE WHEN event_type='emergency_return'      THEN 1 ELSE 0 END) AS emergencies
      FROM delivery_events
     WHERE run_id IS NOT NULL
     GROUP BY run_id
)
SELECT r.run_id,
       r.scenario_names                         AS scenario,
       t.trips                                  AS trips,
       COALESCE(m.maint_required,  0)           AS maint_required,
       COALESCE(m.maint_completed, 0)           AS maint_completed,
       COALESCE(m.emergencies,     0)           AS emergencies,
       ROUND(1.0 * COALESCE(m.maint_required, 0) / NULLIF(t.trips, 0), 4)
                                                 AS maint_required_per_trip,
       ROUND(1.0 * COALESCE(m.emergencies, 0)    / NULLIF(t.trips, 0), 4)
                                                 AS emergency_rate
  FROM simulation_runs r
  LEFT JOIN trip_counts t ON t.run_id = r.run_id
  LEFT JOIN maint        m ON m.run_id = r.run_id
 ORDER BY maint_required_per_trip DESC;
