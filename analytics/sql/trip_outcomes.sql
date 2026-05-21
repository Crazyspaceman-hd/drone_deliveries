-- trip_outcomes.sql
-- Completed vs aborted trips with timestamps + leg counts.

SELECT t.trip_id,
       t.drone_id,
       t.order_id,
       t.status,
       t.launched_at,
       t.completed_at,
       t.legs_completed,
       CASE
         WHEN t.launched_at IS NOT NULL AND t.completed_at IS NOT NULL
           THEN ROUND(
                  (julianday(t.completed_at) - julianday(t.launched_at)) * 86400.0,
                  1)
         ELSE NULL
       END AS duration_seconds
  FROM trips t
 ORDER BY t.status ASC, t.launched_at ASC;
