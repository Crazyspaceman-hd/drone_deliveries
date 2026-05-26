-- snapshot_comparison.sql  (Phase 22)
-- For every trip, list every economics-recompute snapshot side-by-side
-- so an analyst can diff two delivery_domain readings without exporting.
--
-- The trips.estimated_* columns hold whichever domain ran most recently;
-- this view is the durable history.  Use it whenever you need to compare
-- the same operational events under different demand-side assumptions.

SELECT s.trip_id,
       t.scenario_name,
       t.status                                            AS trip_status,
       s.domain_name,
       s.transform_run_id,
       tr.created_at                                       AS computed_at,
       ROUND(s.trip_distance_km,            3)             AS trip_distance_km,
       ROUND(s.estimated_energy_cost,       4)             AS estimated_energy_cost,
       ROUND(s.estimated_maintenance_cost,  4)             AS estimated_maintenance_cost,
       ROUND(s.estimated_operational_cost,  4)             AS estimated_operational_cost,
       ROUND(s.estimated_revenue,           4)             AS estimated_revenue,
       ROUND(s.estimated_profit,            4)             AS estimated_profit,
       ROUND(s.emergency_return_penalty_applied, 4)        AS emergency_penalty
  FROM trip_economics_snapshots s
  JOIN trips                  t  ON t.trip_id          = s.trip_id
  LEFT JOIN transformation_runs tr ON tr.transform_run_id = s.transform_run_id
 ORDER BY t.scenario_name ASC, s.trip_id ASC, tr.created_at ASC;
