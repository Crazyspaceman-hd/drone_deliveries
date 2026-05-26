-- orders_by_status.sql
-- Final order outcomes.

SELECT status,
       COUNT(*) AS n
  FROM orders
 GROUP BY status
 ORDER BY n DESC, status ASC;
