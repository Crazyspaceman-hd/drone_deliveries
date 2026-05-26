-- cross_run_profitability.sql (DuckDB / Parquet)
-- Compare every run side-by-side on profit + completion.

SELECT r.run_id,
       r.scenario_names                                        AS scenario,
       r.seed                                                  AS seed,
       r.simulator_version                                     AS sim_version,
       COUNT(t.trip_id)                                        AS trips,
       SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) AS completed_trips,
       ROUND(100.0 * SUM(CASE WHEN t.status='completed' THEN 1 ELSE 0 END)
             / NULLIF(COUNT(t.trip_id), 0), 2)                  AS completion_rate_pct,
       ROUND(SUM(t.estimated_revenue),         2)              AS total_revenue,
       ROUND(SUM(t.estimated_profit),          2)              AS total_profit,
       ROUND(AVG(t.estimated_profit),          2)              AS avg_profit_per_trip
  FROM simulation_runs r
  LEFT JOIN trips t ON t.run_id = r.run_id
 GROUP BY r.run_id, r.scenario_names, r.seed, r.simulator_version
 ORDER BY total_profit DESC;
