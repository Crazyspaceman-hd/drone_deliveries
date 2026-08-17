# Test strategy (v1.0)

## Guiding rule

> A test belongs in the active suite if its failure would indicate a
> broken current v1 behavior or a broken compatibility contract.

Tests are **not** kept for historical phases whose behavior has been
superseded; they are kept for behavior that v1 still relies on.

## Markers

The suite uses one custom pytest marker (declared in `pytest.ini`):

- `@pytest.mark.slow` — multi-second tests: the 3-scenario × 100-trip
  `multi_scenario_db` builds, chart-rendering, the Cartesian experiment
  run, and CLI subprocess tests.

Run the fast path with `pytest -m "not slow"` (~90 s); the full suite
with `pytest` (~4 min). Both are green at v1.0.

## Classification

| Class | Example files | What a failure means |
|---|---|---|
| **Core contract** | `test_volume_sensitivity.py`, `test_capacity`/`test_parameter_sweeps.py`, `test_service_mixes.py`, `test_delivery_domains.py`, `test_scale_models.py` | A load-bearing analytical formula or the synthetic-name protocol changed behavior. |
| **Portfolio / demo behavior** | `test_portfolio_summary.py`, `test_api.py` (viability, service-mix, parameter-grid endpoints) | The recruiter-facing surfaces (viability grid, pain-points, service mixes, what-if) stopped returning their documented shape. |
| **Integration** | `test_experiments.py`, `test_transforms.py`, `test_runs.py`, `test_api.py` | The pipeline wiring (transforms → snapshots → lineage → API) broke. |
| **Legacy / supporting** | `test_schema.py`, `test_sinks.py`, `test_assumptions.py`, `test_calibration.py`, `test_business_intelligence.py`, `test_hybrid.py`, `test_telemetry.py`, `test_distance_driven.py`, `test_scenarios.py`, `test_parquet_duckdb.py`, `test_validation.py`, `test_simulator.py`, `test_economics.py`, `test_analytics_sql.py` | A foundational Phase 1–23 behavior the analytical layer still sits on top of regressed. |
| **Slow** | any `@pytest.mark.slow` test across the above | Same as the class it belongs to; excluded from the fast path only for runtime. |

## Fixtures

Session-scoped DB fixtures in `tests/conftest.py` (`seed42_db`,
`raw_sim_db`, `multi_scenario_db`, `telemetry_db`, `hybrid_db`) are built
once per run; per-test writable copies use `shutil.copy` (~1 ms) rather
than re-simulating. This is the main lever keeping the fast path under
~90 s.

## Known dead/duplicate tests

None identified at v1.0. The suite was consolidated in Phase 25 (session
fixtures, `slow` markers) and has been kept current per the guiding rule
through Phase 33.
