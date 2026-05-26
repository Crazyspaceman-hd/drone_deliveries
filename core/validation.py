"""
core/validation.py

Lightweight, rule-based data-quality and integrity checks.

What this is
─────────────
A small registry of validation rules that read the operational SQLite
store (and, optionally, the per-run Parquet exports) and return a list
of result dicts.  Each result is one rule firing once; rules surface
the offending row IDs in ``affected_rows`` when they fail so the report
is auditable.

What this is not
─────────────────
- Not Great Expectations or Soda — no schema for "expectations",
  no manifest, no profile reports.
- Not enterprise compliance tooling.
- Not a substitute for the test suite.

Severity levels
────────────────
    INFO  — purely informational (e.g. "no parquet for this run").
    WARN  — divergence that is expected in some cases (trailing
            open maintenance at sim end, optional export missing).
    ERROR — semantic breakage (orphaned run_id, completed trip with
            no terminal event, NaN/negative economics).

Result shape
─────────────
    {
        "rule_name":     "completed_trip_lifecycle",
        "severity":      "ERROR" | "WARN" | "INFO",
        "passed":        bool,
        "details":       "human-readable summary",
        "affected_rows": [<list of IDs>],
        "run_id":        Optional[str],   # set when the rule is run-scoped
    }
"""

from __future__ import annotations

import math
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional


# Severities — strings so they round-trip through JSON / markdown cleanly.
INFO  = "INFO"
WARN  = "WARN"
ERROR = "ERROR"

# Phase 20: validation categories.  Each rule belongs to exactly one.
CAT_SCHEMA       = "schema"          # ingest / column / constraint integrity
CAT_BUSINESS     = "business"        # operational invariants (lifecycle, dispatch)
CAT_CROSS_LAYER  = "cross_layer"     # SQLite ↔ Parquet ↔ DuckDB parity


def _result(
    rule_name: str, severity: str, passed: bool, details: str,
    affected_rows: Optional[Iterable[Any]] = None,
    run_id: Optional[str] = None,
    category: str = CAT_BUSINESS,
) -> dict:
    return {
        "rule_name":     rule_name,
        "category":      category,
        "severity":      severity,
        "passed":        passed,
        "details":       details,
        "affected_rows": list(affected_rows) if affected_rows else [],
        "run_id":        run_id,
    }


def _maybe_run_filter(run_id: Optional[str], col: str = "run_id") -> tuple[str, tuple]:
    """Return (sql_fragment, params) appended to a WHERE clause when run_id is set."""
    if run_id is None:
        return "", ()
    return f" AND {col} = ?", (run_id,)


# ─────────────────────────────────────────────────────────────────────────────
# Rules
# ─────────────────────────────────────────────────────────────────────────────

def _check_completed_trip_lifecycle(
    conn: sqlite3.Connection, run_id: Optional[str]
) -> list[dict]:
    """Every completed trip must have both delivery_completed and
    returned_to_depot events."""
    extra, params = _maybe_run_filter(run_id, "t.run_id")
    missing_delivery = conn.execute(
        f"""
        SELECT t.trip_id FROM trips t
         WHERE t.status = 'completed'{extra}
           AND NOT EXISTS (
                 SELECT 1 FROM delivery_events e
                  WHERE e.trip_id = t.trip_id
                    AND e.event_type = 'delivery_completed'
               )
        """,
        params,
    ).fetchall()
    missing_return = conn.execute(
        f"""
        SELECT t.trip_id FROM trips t
         WHERE t.status = 'completed'{extra}
           AND NOT EXISTS (
                 SELECT 1 FROM delivery_events e
                  WHERE e.trip_id = t.trip_id
                    AND e.event_type = 'returned_to_depot'
               )
        """,
        params,
    ).fetchall()
    md = [r[0] for r in missing_delivery]
    mr = [r[0] for r in missing_return]
    return [
        _result(
            "completed_trip_has_delivery_event", ERROR,
            passed=len(md) == 0,
            details=("all completed trips have delivery_completed events"
                     if not md else
                     f"{len(md)} completed trip(s) missing delivery_completed"),
            affected_rows=md, run_id=run_id, category=CAT_BUSINESS,
        ),
        _result(
            "completed_trip_has_returned_to_depot", ERROR,
            passed=len(mr) == 0,
            details=("all completed trips have returned_to_depot events"
                     if not mr else
                     f"{len(mr)} completed trip(s) missing returned_to_depot"),
            affected_rows=mr, run_id=run_id,
        ),
    ]


def _check_maintenance_lifecycle(
    conn: sqlite3.Connection, run_id: Optional[str]
) -> list[dict]:
    """Open maintenance per drone (required + emergency_return − completed).

    Trailing open maintenance is permitted iff the drone's current
    projection status is 'maintenance' (e.g. the very last trip scheduled
    maintenance and no further dispatch flushed the completion event).
    Everything else is a WARN.
    """
    extra, params = _maybe_run_filter(run_id)
    # Per (run_id, drone_id) because each run is an independent experiment;
    # rolling up across runs would treat trailing-open maintenance in run A
    # as "matched" by a completion in run B, which is wrong.
    rows = conn.execute(
        f"""
        SELECT run_id, drone_id,
               SUM(CASE WHEN event_type='maintenance_required'  THEN 1 ELSE 0 END)
             + SUM(CASE WHEN event_type='emergency_return'      THEN 1 ELSE 0 END)
             - SUM(CASE WHEN event_type='maintenance_completed' THEN 1 ELSE 0 END)
                 AS open_count
          FROM delivery_events
         WHERE drone_id IS NOT NULL AND run_id IS NOT NULL{extra}
         GROUP BY run_id, drone_id
         HAVING open_count <> 0
        """,
        params,
    ).fetchall()
    # Trailing-open is permitted iff the drone is *currently* in maintenance
    # AND this is the most recent run for that drone — i.e. the open cycle
    # is the one still visible in the projection.
    latest_run_per_drone = dict(conn.execute(
        """
        WITH e AS (
            SELECT drone_id, run_id, MAX(event_time) AS last_t
              FROM delivery_events
             WHERE drone_id IS NOT NULL AND run_id IS NOT NULL
             GROUP BY drone_id, run_id
        )
        SELECT drone_id, run_id
          FROM (SELECT drone_id, run_id,
                       ROW_NUMBER() OVER (PARTITION BY drone_id
                                          ORDER BY last_t DESC) AS rn
                  FROM e)
         WHERE rn = 1
        """
    ).fetchall())
    in_maint = {
        r[0] for r in conn.execute(
            "SELECT drone_id FROM drones WHERE status = 'maintenance'"
        ).fetchall()
    }
    suspicious: list[tuple] = []
    trailing:   list[tuple] = []
    for rid, did, open_count in rows:
        is_trailing = (
            open_count == 1
            and did in in_maint
            and latest_run_per_drone.get(did) == rid
        )
        if is_trailing:
            trailing.append((did, open_count))
        else:
            suspicious.append((rid, did, open_count))
    return [
        _result(
            "maintenance_lifecycle_balance", WARN,
            passed=len(suspicious) == 0,
            details=("every maintenance open event is paired with a "
                     "maintenance_completed (trailing-open drones still in "
                     "maintenance status are tolerated)"
                     if not suspicious else
                     f"{len(suspicious)} drone/run pair(s) have unmatched "
                     f"maintenance events outside the trailing-open exception"),
            affected_rows=[f"{rid[:8]}/{d}:{n:+d}" for rid, d, n in suspicious],
            run_id=run_id,
        ),
        _result(
            "maintenance_trailing_open_documented", INFO,
            passed=True,
            details=(f"{len(trailing)} drone(s) ended in maintenance with one "
                     f"open cycle — within tolerance" if trailing
                     else "no trailing-open maintenance cycles"),
            affected_rows=[d for d, _ in trailing],
            run_id=run_id,
        ),
    ]


def _check_drone_multi_assignment(
    conn: sqlite3.Connection, run_id: Optional[str]
) -> list[dict]:
    """No drone may be on two trips with overlapping flight windows.

    Window = [drone_assigned.event_time, returned_to_depot.event_time
              OR emergency_return.event_time] per trip.
    """
    extra, params = _maybe_run_filter(run_id, "t.run_id")
    bounds = conn.execute(
        f"""
        SELECT t.trip_id, t.drone_id, t.run_id,
               MIN(CASE WHEN e.event_type='drone_assigned'                          THEN e.event_time END) AS start_t,
               MAX(CASE WHEN e.event_type IN ('returned_to_depot','emergency_return') THEN e.event_time END) AS end_t
          FROM trips t
          JOIN delivery_events e ON e.trip_id = t.trip_id
         WHERE t.drone_id IS NOT NULL{extra}
         GROUP BY t.trip_id, t.drone_id, t.run_id
        """,
        params,
    ).fetchall()
    overlaps: list[tuple] = []
    # O(n²) per drone+run is fine for our scale; sort by drone+run+start.
    by_drone: dict[tuple, list[tuple]] = {}
    for trip_id, drone_id, rid, s, e in bounds:
        if s is None or e is None:
            continue
        by_drone.setdefault((drone_id, rid), []).append((s, e, trip_id))
    for (drone_id, rid), trips in by_drone.items():
        trips.sort()
        for i in range(len(trips)):
            for j in range(i + 1, len(trips)):
                s_i, e_i, tid_i = trips[i]
                s_j, e_j, tid_j = trips[j]
                if s_j < e_i:    # j starts before i ends → overlap
                    overlaps.append((drone_id, tid_i, tid_j))
    return [_result(
        "drone_no_overlapping_trips", ERROR,
        passed=len(overlaps) == 0,
        details=("no drone is on two trips with overlapping flight windows"
                 if not overlaps else
                 f"{len(overlaps)} overlapping trip pair(s) found"),
        affected_rows=[f"{d}:{a}|{b}" for d, a, b in overlaps],
        run_id=run_id,
    )]


def _check_run_lineage(conn: sqlite3.Connection) -> list[dict]:
    """Every non-null run_id must exist in simulation_runs."""
    results: list[dict] = []
    for table in ("delivery_events", "trips", "orders"):
        rows = conn.execute(
            f"""
            SELECT DISTINCT run_id FROM {table}
             WHERE run_id IS NOT NULL
               AND run_id NOT IN (SELECT run_id FROM simulation_runs)
            """
        ).fetchall()
        orphans = [r[0] for r in rows]
        results.append(_result(
            f"run_lineage_{table}", ERROR,
            passed=len(orphans) == 0,
            details=(f"every {table}.run_id has a matching simulation_runs row"
                     if not orphans else
                     f"{len(orphans)} orphaned run_id(s) in {table}"),
            affected_rows=orphans, category=CAT_SCHEMA,
        ))
    return results


def _check_economic_integrity(
    conn: sqlite3.Connection, run_id: Optional[str]
) -> list[dict]:
    """Terminal trips (completed/aborted) must have sane economic values."""
    extra, params = _maybe_run_filter(run_id)
    rows = conn.execute(
        f"""
        SELECT trip_id, trip_distance_km, estimated_profit,
               estimated_operational_cost, estimated_revenue
          FROM trips
         WHERE status IN ('completed', 'aborted'){extra}
        """,
        params,
    ).fetchall()
    bad: list[str] = []
    for trip_id, dist, profit, op_cost, revenue in rows:
        if dist is None or profit is None or op_cost is None or revenue is None:
            bad.append(trip_id); continue
        if dist < 0 or op_cost < 0 or revenue < 0:
            bad.append(trip_id); continue
        # NaN / inf catch (SQLite stores them as REAL; math handles both).
        for v in (dist, profit, op_cost, revenue):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                bad.append(trip_id); break
    return [_result(
        "economics_finite_and_nonnegative_inputs", ERROR,
        passed=len(bad) == 0,
        details=("all terminal trips have finite, non-negative economic inputs"
                 if not bad else
                 f"{len(bad)} terminal trip(s) have NaN/null/negative economics"),
        affected_rows=bad, run_id=run_id, category=CAT_SCHEMA,
    )]


def _check_projection_consistency(
    conn: sqlite3.Connection, run_id: Optional[str]
) -> list[dict]:
    """Completed trips should record legs_completed = 3."""
    extra, params = _maybe_run_filter(run_id)
    rows = conn.execute(
        f"""
        SELECT trip_id, legs_completed FROM trips
         WHERE status = 'completed'{extra}
           AND legs_completed <> 3
        """,
        params,
    ).fetchall()
    bad = [r[0] for r in rows]
    return [_result(
        "completed_trip_legs_completed_eq_3", WARN,
        passed=len(bad) == 0,
        details=("every completed trip recorded legs_completed = 3"
                 if not bad else
                 f"{len(bad)} completed trip(s) have legs_completed != 3"),
        affected_rows=bad, run_id=run_id,
    )]


def _check_parquet_export_integrity(
    conn: sqlite3.Connection, run_id: Optional[str],
    base_dir: str = "outputs/runs",
) -> list[dict]:
    """Per-run row-count parity between SQLite and the per-run Parquet files.

    INFO when no parquet directory exists for a run (export is opt-in).
    WARN when a parquet exists but row counts disagree.
    Uses pyarrow.parquet.ParquetFile to avoid the dataset-merge gotcha in
    pyarrow ≥ 23.
    """
    run_ids = (
        [run_id] if run_id is not None
        else [r[0] for r in conn.execute(
            "SELECT run_id FROM simulation_runs"
        ).fetchall()]
    )
    if not run_ids:
        return [_result(
            "parquet_row_count_parity", INFO, passed=True,
            details="no simulation runs in database",
            category=CAT_CROSS_LAYER,
        )]

    # Try import here so missing pyarrow becomes INFO, not a crash.
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return [_result(
            "parquet_row_count_parity", INFO, passed=True,
            details="pyarrow not installed; skipping parquet parity check",
            category=CAT_CROSS_LAYER,
        )]

    results: list[dict] = []
    for rid in run_ids:
        pq_dir = Path(base_dir) / f"run_id={rid}" / "parquet"
        if not pq_dir.is_dir():
            results.append(_result(
                "parquet_row_count_parity", INFO,
                passed=True,
                details=(f"no parquet export for run {rid[:8]}… "
                         f"(opt-in via run_scenarios.py --export-parquet)"),
                run_id=rid, category=CAT_CROSS_LAYER,
            ))
            continue
        mismatches: list[str] = []
        for table in ("delivery_events", "trips", "orders"):
            sqlite_n = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (rid,),
            ).fetchone()[0]
            pq_path = pq_dir / f"{table}.parquet"
            if not pq_path.exists():
                mismatches.append(f"{table}:missing"); continue
            parquet_n = pq.ParquetFile(str(pq_path)).metadata.num_rows
            if sqlite_n != parquet_n:
                mismatches.append(f"{table}:sqlite={sqlite_n}/parquet={parquet_n}")
        results.append(_result(
            "parquet_row_count_parity", WARN if mismatches else INFO,
            passed=len(mismatches) == 0,
            details=(
                f"row counts match for run {rid[:8]}…"
                if not mismatches else
                f"row-count mismatch(es) for run {rid[:8]}…: {', '.join(mismatches)}"
            ),
            affected_rows=mismatches, run_id=rid, category=CAT_CROSS_LAYER,
        ))
    return results


def _check_cross_layer_duckdb(
    conn: sqlite3.Connection, run_id: Optional[str],
    base_dir: str = "outputs/runs",
) -> list[dict]:
    """Semantic parity: DuckDB total_profit per run ≈ SQLite total_profit."""
    try:
        from core.duckdb_analytics import (
            discover_run_parquet_dirs, run_duckdb_query,
        )
    except ImportError:
        return [_result(
            "cross_layer_duckdb_profit", INFO, passed=True,
            details="duckdb stack unavailable; skipping cross-layer check",
            category=CAT_CROSS_LAYER,
        )]

    dirs = discover_run_parquet_dirs(base_dir)
    if not dirs:
        return [_result(
            "cross_layer_duckdb_profit", INFO, passed=True,
            details="no parquet directories present; skipping cross-layer check",
            category=CAT_CROSS_LAYER,
        )]
    try:
        _hdr, duck_rows = run_duckdb_query(
            dirs,
            "SELECT run_id, COALESCE(SUM(estimated_profit), 0) "
            "  FROM trips WHERE run_id IS NOT NULL GROUP BY run_id",
        )
    except Exception as exc:    # noqa: BLE001
        return [_result(
            "cross_layer_duckdb_profit", WARN, passed=False,
            details=f"DuckDB cross-layer query failed: {exc}",
            category=CAT_CROSS_LAYER,
        )]

    duck = {rid: float(p or 0) for rid, p in duck_rows}
    sqlite_rows = conn.execute(
        "SELECT run_id, COALESCE(SUM(estimated_profit), 0) "
        "  FROM trips WHERE run_id IS NOT NULL GROUP BY run_id"
    ).fetchall()
    sqlite_map = {rid: float(p or 0) for rid, p in sqlite_rows}

    mismatches: list[str] = []
    for rid, sqlite_val in sqlite_map.items():
        if run_id is not None and rid != run_id:
            continue
        if rid not in duck:
            # No parquet for this run — not a cross-layer failure.
            continue
        # Round to 2 decimals before comparison: economics columns are
        # stored ROUND'd to 4 decimals already.
        if round(sqlite_val, 2) != round(duck[rid], 2):
            mismatches.append(
                f"{rid[:8]}:sqlite={round(sqlite_val,2)}/duckdb={round(duck[rid],2)}"
            )
    return [_result(
        "cross_layer_duckdb_profit", WARN if mismatches else INFO,
        passed=len(mismatches) == 0,
        details=("DuckDB profit aggregates match SQLite for every exported run"
                 if not mismatches else
                 f"{len(mismatches)} run(s) disagree on total_profit"),
        affected_rows=mismatches, run_id=run_id, category=CAT_CROSS_LAYER,
    )]


# ─────────────────────────────────────────────────────────────────────────────
# Public surface
# ─────────────────────────────────────────────────────────────────────────────

def run_validation_checks(
    db_path: str, run_id: Optional[str] = None,
) -> list[dict]:
    """Run every validation rule and return a flat list of result dicts."""
    if not os.path.exists(db_path):
        return [_result(
            "database_exists", ERROR, passed=False,
            details=f"database not found at {db_path}",
            category=CAT_SCHEMA,
        )]
    conn = sqlite3.connect(db_path)
    try:
        results: list[dict] = []
        results.extend(_check_completed_trip_lifecycle(conn, run_id))
        results.extend(_check_maintenance_lifecycle(conn, run_id))
        results.extend(_check_drone_multi_assignment(conn, run_id))
        if run_id is None:
            # Lineage is global — only meaningful when scanning the whole DB.
            results.extend(_check_run_lineage(conn))
        results.extend(_check_economic_integrity(conn, run_id))
        results.extend(_check_projection_consistency(conn, run_id))
        results.extend(_check_parquet_export_integrity(conn, run_id))
        results.extend(_check_cross_layer_duckdb(conn, run_id))
    finally:
        conn.close()
    return results


def validate_run(db_path: str, run_id: str) -> list[dict]:
    """Alias: same as run_validation_checks(db_path, run_id=run_id)."""
    return run_validation_checks(db_path, run_id=run_id)


def generate_validation_summary(
    db_path: str, run_id: Optional[str] = None,
) -> dict:
    """Bundle results + headline counts for the CLI / report."""
    results = run_validation_checks(db_path, run_id=run_id)
    by_sev: dict[str, int] = {INFO: 0, WARN: 0, ERROR: 0}
    failed: dict[str, int] = {INFO: 0, WARN: 0, ERROR: 0}
    by_cat: dict[str, int] = {CAT_SCHEMA: 0, CAT_BUSINESS: 0, CAT_CROSS_LAYER: 0}
    failed_by_cat: dict[str, int] = {CAT_SCHEMA: 0, CAT_BUSINESS: 0, CAT_CROSS_LAYER: 0}
    for r in results:
        by_sev[r["severity"]]  = by_sev.get(r["severity"],  0) + 1
        by_cat[r.get("category", CAT_BUSINESS)] = (
            by_cat.get(r.get("category", CAT_BUSINESS), 0) + 1
        )
        if not r["passed"]:
            failed[r["severity"]] = failed.get(r["severity"], 0) + 1
            failed_by_cat[r.get("category", CAT_BUSINESS)] = (
                failed_by_cat.get(r.get("category", CAT_BUSINESS), 0) + 1
            )
    return {
        "run_id":             run_id,
        "results":            results,
        "counts_by_severity": by_sev,
        "failed_by_severity": failed,
        "counts_by_category": by_cat,
        "failed_by_category": failed_by_cat,
        "any_errors":         failed[ERROR] > 0,
    }
