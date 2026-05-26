-- event_volume_by_run.sql (DuckDB / Parquet)
-- Event counts by type, grouped by run.  Useful for sanity-checking that
-- runs with different scenarios produce visibly different volumes.

SELECT run_id,
       event_type,
       COUNT(*) AS events
  FROM delivery_events
 WHERE run_id IS NOT NULL
 GROUP BY run_id, event_type
 ORDER BY run_id ASC, events DESC;
