-- telemetry_summary.sql
-- Per-scenario telemetry aggregates over the raw observation table.
-- Computed live in SQL (no dependency on the telemetry transform's
-- summary table) so analysts can run this without running transforms.

SELECT de.scenario_name,
       COUNT(*)                                          AS pings,
       ROUND(AVG(t.altitude_m),                    2)    AS avg_altitude_m,
       ROUND(AVG(t.airspeed_mps),                  2)    AS avg_airspeed_mps,
       ROUND(AVG(t.battery_temp_c),                2)    AS avg_battery_temp_c,
       ROUND(MAX(t.battery_temp_c),                2)    AS max_battery_temp_c,
       ROUND(AVG(t.motor_temp_c),                  2)    AS avg_motor_temp_c,
       ROUND(MAX(t.motor_temp_c),                  2)    AS max_motor_temp_c,
       ROUND(AVG(t.signal_strength_pct),           2)    AS avg_signal_pct,
       ROUND(AVG(t.gps_signal_quality),            2)    AS avg_gps_quality,
       ROUND(AVG(t.estimated_remaining_range_km),  3)    AS avg_remaining_range_km,
       SUM(CASE WHEN t.battery_temp_c > 50 THEN 1 ELSE 0 END) AS battery_hot_pings,
       SUM(CASE WHEN t.motor_temp_c   > 85 THEN 1 ELSE 0 END) AS motor_hot_pings
  FROM delivery_events de
  JOIN telemetry_observations t ON t.event_id = de.event_id
 WHERE de.scenario_name IS NOT NULL
 GROUP BY de.scenario_name
 ORDER BY de.scenario_name ASC;
