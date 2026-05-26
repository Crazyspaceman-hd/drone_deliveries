"""
transforms/telemetry.py

Derived telemetry summaries (Phase 21).

The simulator emits raw telemetry observations into the
``telemetry_observations`` side table.  This transform reads those
observations + the matching ``delivery_events`` rows, computes per-run
and per-scenario summaries, and writes them into a small
``telemetry_summaries`` table so the API and charts can hit a flat
single-row-per-(run, scenario) view.

What's derived here (not on the source layer)
─────────────────────────────────────────────
* avg / max battery temp, motor temp
* avg airspeed, altitude
* avg signal strength, gps quality
* anomaly counts (battery_temp > 50, motor_temp > 85, signal < 60, etc.)
* obstacle-warning rate per trip

Lineage row goes into ``transformation_runs`` like every other transform.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from transforms.runs import record_transform_run

TRANSFORM_NAME    = "telemetry"
TRANSFORM_VERSION = "telemetry.v1"

# Phase 20 declarative ordering — the runner sorts transforms by this.
# Telemetry depends on the raw observations only; safe to run after the
# others without affecting them.
RUN_ORDER = 30   # economics=10, hybrid=20, telemetry=30


# Anomaly thresholds — visible at top of file for retuning.
BATTERY_TEMP_HOT_C   = 50.0    # above optimal envelope
MOTOR_TEMP_HOT_C     = 85.0    # nearing thermal limit (limit ~95)
SIGNAL_WEAK_PCT      = 60.0    # link degraded
GPS_DEGRADED_QUALITY = 60.0    # fix degraded


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telemetry_summaries (
            run_id            TEXT,
            scenario_name     TEXT,
            ping_count        INTEGER,
            avg_altitude_m    REAL,
            avg_airspeed_mps  REAL,
            avg_battery_temp_c REAL,
            max_battery_temp_c REAL,
            avg_motor_temp_c  REAL,
            max_motor_temp_c  REAL,
            avg_signal_pct    REAL,
            avg_gps_quality   REAL,
            avg_remaining_range_km REAL,
            battery_temp_hot_count   INTEGER,
            motor_temp_hot_count     INTEGER,
            signal_weak_count        INTEGER,
            gps_degraded_count       INTEGER,
            obstacle_warning_count   INTEGER,
            PRIMARY KEY (run_id, scenario_name)
        )
    """)


def run(
    db_path: str,
    *,
    run_id: Optional[str] = None,
) -> dict:
    """Compute per-(run, scenario) telemetry summaries and UPSERT.

    Args:
        db_path: SQLite file.
        run_id:  Limit to one simulation run.  None = every run in the DB.
    """
    conn = sqlite3.connect(db_path)
    try:
        _ensure_table(conn)
        cur = conn.cursor()

        where = ""
        params: tuple = ()
        if run_id is not None:
            where = " WHERE de.run_id = ?"
            params = (run_id,)

        # Per-(run, scenario) aggregate over telemetry pings + their
        # side-table observations.
        rows = cur.execute(
            f"""
            SELECT de.run_id,
                   de.scenario_name,
                   COUNT(*)                              AS ping_count,
                   AVG(t.altitude_m)                     AS avg_altitude,
                   AVG(t.airspeed_mps)                   AS avg_airspeed,
                   AVG(t.battery_temp_c)                 AS avg_batt_temp,
                   MAX(t.battery_temp_c)                 AS max_batt_temp,
                   AVG(t.motor_temp_c)                   AS avg_motor_temp,
                   MAX(t.motor_temp_c)                   AS max_motor_temp,
                   AVG(t.signal_strength_pct)            AS avg_signal,
                   AVG(t.gps_signal_quality)             AS avg_gps,
                   AVG(t.estimated_remaining_range_km)   AS avg_range,
                   SUM(CASE WHEN t.battery_temp_c > ?    THEN 1 ELSE 0 END) AS batt_hot,
                   SUM(CASE WHEN t.motor_temp_c   > ?    THEN 1 ELSE 0 END) AS motor_hot,
                   SUM(CASE WHEN t.signal_strength_pct < ? THEN 1 ELSE 0 END) AS sig_weak,
                   SUM(CASE WHEN t.gps_signal_quality  < ? THEN 1 ELSE 0 END) AS gps_bad
              FROM delivery_events de
              JOIN telemetry_observations t ON t.event_id = de.event_id
            {where}
             GROUP BY de.run_id, de.scenario_name
            """,
            (BATTERY_TEMP_HOT_C, MOTOR_TEMP_HOT_C,
             SIGNAL_WEAK_PCT, GPS_DEGRADED_QUALITY) + params,
        ).fetchall()

        # Obstacle-warning count by (run, scenario) — separate query because
        # those events have no row in telemetry_observations.
        obstacle_counts = dict(cur.execute(
            f"""
            SELECT (de.run_id || '|' || de.scenario_name) AS k,
                   COUNT(*)
              FROM delivery_events de
             WHERE de.event_type = 'obstacle_warning'
               {"AND de.run_id = ?" if run_id is not None else ""}
             GROUP BY de.run_id, de.scenario_name
            """,
            params,
        ).fetchall())

        rows_updated = 0
        for (rid, scen, n, alt, airs, abt, mbt, amt, mmt, asig, agps, arange,
             bh, mh, sw, gb) in rows:
            obstacle_n = obstacle_counts.get(f"{rid}|{scen}", 0)
            cur.execute(
                """
                INSERT OR REPLACE INTO telemetry_summaries (
                    run_id, scenario_name, ping_count,
                    avg_altitude_m, avg_airspeed_mps,
                    avg_battery_temp_c, max_battery_temp_c,
                    avg_motor_temp_c,   max_motor_temp_c,
                    avg_signal_pct, avg_gps_quality, avg_remaining_range_km,
                    battery_temp_hot_count, motor_temp_hot_count,
                    signal_weak_count, gps_degraded_count,
                    obstacle_warning_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rid, scen, int(n or 0),
                 round(alt  or 0.0, 2), round(airs or 0.0, 2),
                 round(abt  or 0.0, 2), round(mbt  or 0.0, 2),
                 round(amt  or 0.0, 2), round(mmt  or 0.0, 2),
                 round(asig or 0.0, 2), round(agps or 0.0, 2),
                 round(arange or 0.0, 3),
                 int(bh or 0), int(mh or 0),
                 int(sw or 0), int(gb or 0),
                 int(obstacle_n)),
            )
            rows_updated += 1
        conn.commit()
    finally:
        conn.close()

    tx_id = record_transform_run(
        db_path,
        source_run_id     = run_id,
        transform_name    = TRANSFORM_NAME,
        transform_version = TRANSFORM_VERSION,
        row_count         = rows_updated,
    )
    return {
        "transform_run_id":  tx_id,
        "transform_name":    TRANSFORM_NAME,
        "transform_version": TRANSFORM_VERSION,
        "source_run_id":     run_id,
        "rows_updated":      rows_updated,
    }
