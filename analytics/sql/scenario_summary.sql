-- scenario_summary.sql
-- Per-scenario operational summary.
--
-- Trip-level counts come from the trips projection (cheap and authoritative).
-- Event-level counts come from delivery_events, joined back to trips when
-- the event itself is trip-scoped or via its own scenario_name tag when not
-- (e.g. maintenance events fired between trips).

WITH trip_stats AS (
    SELECT scenario_name,
           COUNT(*)                                          AS trips_requested,
           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS trips_completed,
           SUM(CASE WHEN status = 'aborted'   THEN 1 ELSE 0 END) AS trips_aborted,
           ROUND(AVG(
             CASE
               WHEN launched_at IS NOT NULL AND completed_at IS NOT NULL
                 THEN (julianday(completed_at) - julianday(launched_at)) * 86400.0
               ELSE NULL
             END
           ), 1) AS avg_trip_duration_seconds
      FROM trips
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
),
event_stats AS (
    SELECT scenario_name,
           COUNT(*)                                                            AS events_total,
           SUM(CASE WHEN event_type = 'battery_warning'      THEN 1 ELSE 0 END) AS battery_warnings,
           SUM(CASE WHEN event_type = 'emergency_return'     THEN 1 ELSE 0 END) AS emergency_returns,
           SUM(CASE WHEN event_type = 'maintenance_required' THEN 1 ELSE 0 END) AS maintenance_required,
           SUM(CASE WHEN event_type = 'route_deviation'      THEN 1 ELSE 0 END) AS route_deviations
      FROM delivery_events
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
)
SELECT t.scenario_name,
       t.trips_requested,
       t.trips_completed,
       t.trips_aborted,
       t.avg_trip_duration_seconds,
       COALESCE(e.events_total, 0)              AS events_total,
       ROUND(CAST(COALESCE(e.events_total, 0) AS REAL) / NULLIF(t.trips_requested, 0), 1)
                                                AS avg_events_per_trip,
       COALESCE(e.battery_warnings, 0)          AS battery_warnings,
       COALESCE(e.emergency_returns, 0)         AS emergency_returns,
       COALESCE(e.maintenance_required, 0)      AS maintenance_required,
       COALESCE(e.route_deviations, 0)          AS route_deviations
  FROM trip_stats t
  LEFT JOIN event_stats e ON e.scenario_name = t.scenario_name
 ORDER BY t.scenario_name ASC;
