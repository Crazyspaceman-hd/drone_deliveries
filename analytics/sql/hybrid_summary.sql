-- hybrid_summary.sql
-- Per-scenario fulfillment-mode split + hybrid-relevant latency comparison.
--
-- "Hybrid" here is the strategy that follows the activation rules in
-- core/hybrid.py.  We compare the average latency a hybrid dispatcher
-- *would have* achieved against trucks-only and drones-only baselines.

WITH counts AS (
    SELECT scenario_name,
           COUNT(*)                                                 AS orders,
           SUM(CASE WHEN fulfillment_mode='TRUCK'  THEN 1 ELSE 0 END) AS truck_orders,
           SUM(CASE WHEN fulfillment_mode='DRONE'  THEN 1 ELSE 0 END) AS drone_orders,
           SUM(CASE WHEN fulfillment_mode='HYBRID' THEN 1 ELSE 0 END) AS hybrid_orders,
           SUM(CASE WHEN premium_delivery=1        THEN 1 ELSE 0 END) AS premium_orders,
           AVG(truck_baseline_latency_min)                            AS avg_truck_latency,
           AVG(drone_estimated_latency_min)                           AS avg_drone_latency,
           AVG(CASE WHEN fulfillment_mode='TRUCK'
                    THEN truck_baseline_latency_min
                    ELSE drone_estimated_latency_min
               END)                                                    AS avg_hybrid_latency,
           AVG(queue_pressure)                                         AS avg_queue_pressure,
           AVG(congestion_factor)                                      AS avg_congestion
      FROM orders
     WHERE fulfillment_mode IS NOT NULL
     GROUP BY scenario_name
)
SELECT scenario_name,
       orders,
       truck_orders,
       drone_orders,
       hybrid_orders,
       premium_orders,
       ROUND(100.0 * drone_orders / NULLIF(orders, 0), 1)   AS drone_activation_pct,
       ROUND(100.0 * (drone_orders + hybrid_orders)
                       / NULLIF(orders, 0), 1)              AS drone_or_hybrid_pct,
       ROUND(avg_truck_latency,  2)                         AS avg_truck_latency_min,
       ROUND(avg_drone_latency,  2)                         AS avg_drone_latency_min,
       ROUND(avg_hybrid_latency, 2)                         AS avg_hybrid_latency_min,
       ROUND(avg_truck_latency - avg_hybrid_latency, 2)     AS hybrid_latency_savings_min,
       ROUND(avg_queue_pressure, 3)                         AS avg_queue_pressure,
       ROUND(avg_congestion,     3)                         AS avg_congestion
  FROM counts
 ORDER BY scenario_name ASC;
