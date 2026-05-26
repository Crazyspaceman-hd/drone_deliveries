-- scale_model_comparison.sql  (Phase 23)
-- Per (scale_model_name, scenario_name): operational cost (physics),
-- amortized overhead (scale overlay), effective profit (operational +
-- overhead + utilization rebate), and a break-even indicator.
--
-- Joins:
--   trip_scale_snapshots ── source_snapshot_run_id ──▶ trip_economics_snapshots
--                       └── trip_id ──▶ trips (for scenario_name)
--
-- The economics row supplies the per-trip operational cost; the scale
-- row supplies amortized overhead + effective profit.  Two separate
-- tables (Phase 22 + Phase 23), one join.

SELECT s.scale_model_name,
       t.scenario_name,
       COUNT(*)                                       AS trips,
       ROUND(AVG(e.estimated_operational_cost), 2)    AS avg_operational_cost,
       ROUND(AVG(s.amortized_overhead_per_trip), 2)   AS avg_amortized_overhead_per_trip,
       ROUND(AVG(s.effective_profit),           2)    AS avg_effective_profit,
       ROUND(AVG(s.utilization_efficiency),     3)    AS avg_utilization_efficiency,
       SUM(CASE WHEN s.effective_profit > 0 THEN 1 ELSE 0 END)
                                                      AS trips_with_effective_profit_positive
  FROM trip_scale_snapshots      s
  JOIN trip_economics_snapshots  e
       ON  e.transform_run_id    = s.source_snapshot_run_id
       AND e.trip_id              = s.trip_id
  JOIN trips                     t
       ON  t.trip_id              = s.trip_id
 GROUP BY s.scale_model_name, t.scenario_name
 ORDER BY s.scale_model_name ASC, t.scenario_name ASC;
