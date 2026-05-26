-- validation_summary.sql
-- Per-run integrity counts that the Python validation layer (core/validation.py)
-- also enforces.  This file is a standalone SQL view for analyst use.
--
-- A run is healthy when every "*_violations" column is 0.

WITH trips_lifecycle AS (
    SELECT t.run_id,
           SUM(CASE WHEN t.status = 'completed' AND NOT EXISTS (
                       SELECT 1 FROM delivery_events e
                        WHERE e.trip_id = t.trip_id
                          AND e.event_type = 'delivery_completed'
                   ) THEN 1 ELSE 0 END)                              AS missing_delivery_completed,
           SUM(CASE WHEN t.status = 'completed' AND NOT EXISTS (
                       SELECT 1 FROM delivery_events e
                        WHERE e.trip_id = t.trip_id
                          AND e.event_type = 'returned_to_depot'
                   ) THEN 1 ELSE 0 END)                              AS missing_returned_to_depot,
           SUM(CASE WHEN t.status = 'completed' AND t.legs_completed <> 3
                    THEN 1 ELSE 0 END)                                AS legs_completed_violations
      FROM trips t
     WHERE t.run_id IS NOT NULL
     GROUP BY t.run_id
),
maintenance_open AS (
    SELECT run_id,
           COUNT(*) AS open_count
      FROM (
           SELECT run_id, drone_id,
                  SUM(CASE WHEN event_type='maintenance_required'  THEN 1 ELSE 0 END)
                + SUM(CASE WHEN event_type='emergency_return'      THEN 1 ELSE 0 END)
                - SUM(CASE WHEN event_type='maintenance_completed' THEN 1 ELSE 0 END)
                    AS open_balance
             FROM delivery_events
            WHERE drone_id IS NOT NULL AND run_id IS NOT NULL
            GROUP BY run_id, drone_id
            HAVING open_balance <> 0
      ) x
     GROUP BY run_id
),
economics AS (
    SELECT run_id,
           SUM(CASE WHEN status IN ('completed','aborted')
                     AND (trip_distance_km IS NULL OR trip_distance_km < 0
                          OR estimated_profit IS NULL
                          OR estimated_operational_cost IS NULL
                          OR estimated_operational_cost < 0)
                    THEN 1 ELSE 0 END) AS economic_violations
      FROM trips
     WHERE run_id IS NOT NULL
     GROUP BY run_id
)
SELECT r.run_id,
       r.scenario_names                                     AS scenario,
       COALESCE(l.missing_delivery_completed, 0)            AS missing_delivery_completed,
       COALESCE(l.missing_returned_to_depot,  0)            AS missing_returned_to_depot,
       COALESCE(l.legs_completed_violations,  0)            AS legs_completed_violations,
       COALESCE(m.open_count,                  0)           AS maintenance_lifecycle_imbalances,
       COALESCE(e.economic_violations,         0)           AS economic_violations,
         COALESCE(l.missing_delivery_completed, 0)
       + COALESCE(l.missing_returned_to_depot,  0)
       + COALESCE(l.legs_completed_violations,  0)
       + COALESCE(m.open_count,                  0)
       + COALESCE(e.economic_violations,         0)         AS total_violations
  FROM simulation_runs r
  LEFT JOIN trips_lifecycle l ON l.run_id = r.run_id
  LEFT JOIN maintenance_open m ON m.run_id = r.run_id
  LEFT JOIN economics        e ON e.run_id = r.run_id
 ORDER BY total_violations DESC, r.created_at DESC;
