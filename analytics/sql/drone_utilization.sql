-- drone_utilization.sql
-- Per-drone activity summary.
--
-- Joins the drones projection (final status, battery, trips_flown) against
-- counts of operational event types from delivery_events.

WITH ev AS (
    SELECT drone_id,
           SUM(CASE WHEN event_type = 'telemetry_ping'        THEN 1 ELSE 0 END) AS telemetry_events,
           SUM(CASE WHEN event_type = 'route_deviation'       THEN 1 ELSE 0 END) AS route_deviation_events,
           SUM(CASE WHEN event_type = 'battery_warning'       THEN 1 ELSE 0 END) AS battery_warning_events,
           SUM(CASE WHEN event_type = 'maintenance_required'  THEN 1 ELSE 0 END) AS maintenance_required_events,
           SUM(CASE WHEN event_type = 'maintenance_completed' THEN 1 ELSE 0 END) AS maintenance_completed_events,
           SUM(CASE WHEN event_type = 'emergency_return'      THEN 1 ELSE 0 END) AS emergency_return_events,
           SUM(CASE WHEN event_type = 'returned_to_depot'     THEN 1 ELSE 0 END) AS returned_to_depot_events
      FROM delivery_events
     WHERE drone_id IS NOT NULL
     GROUP BY drone_id
)
SELECT d.drone_id,
       d.trips_flown,
       d.status                                  AS final_status,
       ROUND(d.battery_pct, 1)                   AS final_battery_pct,
       COALESCE(ev.telemetry_events,            0) AS telemetry_events,
       COALESCE(ev.route_deviation_events,      0) AS route_deviation_events,
       COALESCE(ev.battery_warning_events,      0) AS battery_warning_events,
       COALESCE(ev.maintenance_required_events,  0) AS maintenance_required_events,
       COALESCE(ev.maintenance_completed_events, 0) AS maintenance_completed_events,
       COALESCE(ev.emergency_return_events,      0) AS emergency_return_events,
       COALESCE(ev.returned_to_depot_events,     0) AS returned_to_depot_events
  FROM drones d
  LEFT JOIN ev ON ev.drone_id = d.drone_id
 ORDER BY d.drone_id ASC;
