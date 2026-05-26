-- event_counts.sql
-- Count events by type.  Sanity check for the simulator output.

SELECT event_type,
       COUNT(*) AS n
  FROM delivery_events
 GROUP BY event_type
 ORDER BY n DESC, event_type ASC;
