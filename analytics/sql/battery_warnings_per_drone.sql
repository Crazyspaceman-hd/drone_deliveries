-- battery_warnings_per_drone.sql
-- Per-drone battery health: warning count, lowest reading seen, latest reading.

WITH battery_obs AS (
    SELECT drone_id,
           battery_pct,
           event_time,
           event_type
      FROM delivery_events
     WHERE drone_id    IS NOT NULL
       AND battery_pct IS NOT NULL
),
latest AS (
    SELECT b.drone_id,
           b.battery_pct AS latest_battery_pct
      FROM battery_obs b
      JOIN (
            SELECT drone_id, MAX(event_time) AS max_t
              FROM battery_obs
             GROUP BY drone_id
           ) m
        ON m.drone_id = b.drone_id
       AND m.max_t    = b.event_time
)
SELECT d.drone_id,
       SUM(CASE WHEN e.event_type = 'battery_warning' THEN 1 ELSE 0 END) AS battery_warning_count,
       ROUND(MIN(e.battery_pct), 1)               AS min_battery_pct_seen,
       ROUND(MAX(l.latest_battery_pct), 1)        AS latest_battery_pct
  FROM drones d
  LEFT JOIN delivery_events e ON e.drone_id = d.drone_id
  LEFT JOIN latest          l ON l.drone_id = d.drone_id
 GROUP BY d.drone_id
 ORDER BY battery_warning_count DESC, d.drone_id ASC;
