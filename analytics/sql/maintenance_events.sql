-- maintenance_events.sql
-- Per-drone maintenance activity and current status.

SELECT d.drone_id,
       SUM(CASE WHEN e.event_type = 'maintenance_required'  THEN 1 ELSE 0 END) AS maintenance_required_events,
       SUM(CASE WHEN e.event_type = 'maintenance_completed' THEN 1 ELSE 0 END) AS maintenance_completed_events,
       d.status AS latest_status
  FROM drones d
  LEFT JOIN delivery_events e
    ON e.drone_id = d.drone_id
 GROUP BY d.drone_id, d.status
 ORDER BY maintenance_required_events DESC, d.drone_id ASC;
