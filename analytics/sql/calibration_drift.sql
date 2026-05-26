-- calibration_drift.sql
-- Observed vs configured per-scenario rates, with a drift column for each
-- metric.
--
-- The "configured" CTE below mirrors the values in core/scenarios.py for
-- the three built-in scenarios.  This is a duplication on purpose: the
-- SQL file should stand on its own for ad-hoc analyst use.  If you add a
-- new scenario or change the knobs, update this CTE as well.
--
-- Drift convention: drift = observed - configured  (positive = exceeded).

WITH configured (scenario_name,
                 cfg_emergency_return_chance,
                 cfg_maintenance_chance,
                 cfg_route_deviation_chance,
                 cfg_avg_trip_distance_km) AS (
    SELECT 'urban_dense',       0.02, 0.06, 0.10,  3.0  UNION ALL
    SELECT 'suburban_standard', 0.05, 0.08, 0.05,  6.0  UNION ALL
    SELECT 'rural_extended',    0.10, 0.12, 0.02, 12.0
),
trip_stats AS (
    SELECT scenario_name,
           COUNT(*)                                            AS trips,
           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
           AVG(trip_distance_km)                               AS obs_avg_distance_km,
           AVG(estimated_profit)                               AS avg_profit_per_trip
      FROM trips
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
),
event_stats AS (
    SELECT scenario_name,
           SUM(CASE WHEN event_type='emergency_return'     THEN 1 ELSE 0 END) AS emerg,
           SUM(CASE WHEN event_type='maintenance_required' THEN 1 ELSE 0 END) AS maint,
           SUM(CASE WHEN event_type='route_deviation'      THEN 1 ELSE 0 END) AS route_dev,
           SUM(CASE WHEN event_type='telemetry_ping'       THEN 1 ELSE 0 END) AS pings
      FROM delivery_events
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
)
SELECT t.scenario_name,
       -- configured side
       c.cfg_emergency_return_chance,
       c.cfg_maintenance_chance,
       c.cfg_route_deviation_chance,
       c.cfg_avg_trip_distance_km,
       -- observed side
       ROUND(1.0 * COALESCE(e.emerg, 0)     / NULLIF(t.trips, 0), 4) AS observed_emergency_return_rate,
       ROUND(1.0 * COALESCE(e.maint, 0)     / NULLIF(t.trips, 0), 4) AS observed_maintenance_rate,
       ROUND(1.0 * COALESCE(e.route_dev, 0) / NULLIF(COALESCE(e.pings, 0), 0), 4)
                                                                    AS observed_route_deviation_rate,
       ROUND(t.obs_avg_distance_km,                                3) AS observed_avg_trip_distance_km,
       ROUND(100.0 * t.completed / NULLIF(t.trips, 0),              2) AS completion_rate_pct,
       ROUND(t.avg_profit_per_trip,                                 2) AS avg_profit_per_trip,
       -- drifts (observed - configured)
       ROUND(1.0 * COALESCE(e.emerg, 0) / NULLIF(t.trips, 0) - c.cfg_emergency_return_chance, 4)
           AS emergency_return_drift,
       ROUND(1.0 * COALESCE(e.maint, 0) / NULLIF(t.trips, 0) - c.cfg_maintenance_chance, 4)
           AS maintenance_drift,
       ROUND(1.0 * COALESCE(e.route_dev, 0) / NULLIF(COALESCE(e.pings, 0), 0)
             - c.cfg_route_deviation_chance, 4)
           AS route_deviation_drift,
       ROUND(t.obs_avg_distance_km - c.cfg_avg_trip_distance_km, 3) AS avg_trip_distance_drift_km
  FROM trip_stats t
  LEFT JOIN event_stats e ON e.scenario_name = t.scenario_name
  LEFT JOIN configured  c ON c.scenario_name = t.scenario_name
 ORDER BY t.scenario_name ASC;
