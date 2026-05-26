"""Transformation layer (Phase 20 decomposition).

Conceptually:

    simulator      → raw operational events                 (source system)
    transforms/    → derived analytical state                (you are here)
    analytics/     → aggregations, BI, calibration, charts  (downstream)

Each transform module exposes a single ``run(...)`` entry point that:

* reads from the raw tables in SQLite (delivery_events, trips, orders),
* derives analytical state,
* writes back into the existing derived columns on trips / orders,
* records one row in ``transformation_runs`` for lineage.

Transforms are deterministic and rerunnable — changing their parameters
should regenerate derived state without re-running the simulator.
"""
