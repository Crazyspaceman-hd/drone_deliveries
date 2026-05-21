"""
core/visualizations.py

Static PNG charts derived from the SQLite event store.

Reads only; no writes to the database, no simulator coupling.  Uses
matplotlib with the non-interactive Agg backend so tests and headless
runs do not need a display.

Public entry point::

    from core.visualizations import generate_charts
    paths = generate_charts(db_path="data/delivery_system.sqlite",
                            out_dir="outputs/charts")
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # must be set before importing pyplot
import matplotlib.pyplot as plt


CHART_FILENAMES = {
    "event_counts":             "event_counts.png",
    "trip_outcomes":            "trip_outcomes.png",
    "drone_utilization":        "drone_utilization.png",
    "battery_warnings":         "battery_warnings_by_drone.png",
    "battery_over_time":        "battery_over_time.png",
}


# ─────────────────────────────────────────────────────────────────────────────
# Small SQL helpers (no ORM, plain tuples)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def _save(fig, out_path: str) -> str:
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Individual chart builders
# ─────────────────────────────────────────────────────────────────────────────

def _chart_event_counts(conn: sqlite3.Connection, out_path: str) -> str:
    rows = _fetch(conn,
        "SELECT event_type, COUNT(*) FROM delivery_events "
        "GROUP BY event_type ORDER BY COUNT(*) DESC, event_type ASC"
    )
    labels = [r[0] for r in rows]
    counts = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(labels, counts, color="steelblue")
    ax.set_title("Drone Delivery Events by Type")
    ax.set_xlabel("event_type")
    ax.set_ylabel("count")
    ax.tick_params(axis="x", rotation=35)
    for tick in ax.get_xticklabels():
        tick.set_ha("right")
    return _save(fig, out_path)


def _chart_trip_outcomes(conn: sqlite3.Connection, out_path: str) -> str:
    rows = _fetch(conn,
        "SELECT status, COUNT(*) FROM trips GROUP BY status ORDER BY status ASC"
    )
    labels = [r[0] for r in rows]
    counts = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(6, 4))
    colors = ["seagreen" if l == "completed" else "indianred" if l == "aborted"
              else "slategray" for l in labels]
    ax.bar(labels, counts, color=colors)
    ax.set_title("Trip Outcomes")
    ax.set_xlabel("status")
    ax.set_ylabel("count")
    return _save(fig, out_path)


def _chart_drone_utilization(conn: sqlite3.Connection, out_path: str) -> str:
    rows = _fetch(conn,
        "SELECT drone_id, trips_flown FROM drones ORDER BY drone_id ASC"
    )
    labels = [r[0] for r in rows]
    counts = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels, counts, color="darkorange")
    ax.set_title("Trips Flown by Drone")
    ax.set_xlabel("drone_id")
    ax.set_ylabel("trips_flown")
    return _save(fig, out_path)


def _chart_battery_warnings(conn: sqlite3.Connection, out_path: str) -> str:
    # Include every known drone, even with zero warnings, so the chart is
    # always self-explanatory.
    drones = [r[0] for r in _fetch(conn,
        "SELECT drone_id FROM drones ORDER BY drone_id ASC"
    )]
    warning_counts = dict(_fetch(conn,
        "SELECT drone_id, COUNT(*) FROM delivery_events "
        "WHERE event_type = 'battery_warning' AND drone_id IS NOT NULL "
        "GROUP BY drone_id"
    ))
    counts = [warning_counts.get(d, 0) for d in drones]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(drones, counts, color="crimson")
    ax.set_title("Battery Warnings by Drone")
    ax.set_xlabel("drone_id")
    ax.set_ylabel("battery_warning events")
    return _save(fig, out_path)


def _chart_battery_over_time(conn: sqlite3.Connection, out_path: str) -> str:
    rows = _fetch(conn,
        "SELECT drone_id, event_time, battery_pct FROM delivery_events "
        "WHERE drone_id IS NOT NULL AND battery_pct IS NOT NULL "
        "ORDER BY drone_id ASC, event_time ASC"
    )

    series: dict[str, tuple[list[datetime], list[float]]] = {}
    for drone_id, ts, battery in rows:
        when = _parse_iso(ts)
        if when is None:
            continue
        xs, ys = series.setdefault(drone_id, ([], []))
        xs.append(when)
        ys.append(float(battery))

    fig, ax = plt.subplots(figsize=(10, 5))
    for drone_id in sorted(series.keys()):
        xs, ys = series[drone_id]
        ax.plot(xs, ys, marker="", linewidth=1.2, label=drone_id)
    ax.set_title("Battery Percentage Over Time")
    ax.set_xlabel("event_time")
    ax.set_ylabel("battery_pct")
    ax.set_ylim(0, 100)
    if series:
        ax.legend(loc="best", fontsize=8)
    fig.autofmt_xdate()
    return _save(fig, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_charts(
    db_path: str = "data/delivery_system.sqlite",
    out_dir: str = "outputs/charts",
) -> dict[str, str]:
    """Build all charts from db_path into out_dir; return {name: file_path}."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"database not found: {db_path}")
    os.makedirs(out_dir, exist_ok=True)

    builders = {
        "event_counts":      _chart_event_counts,
        "trip_outcomes":     _chart_trip_outcomes,
        "drone_utilization": _chart_drone_utilization,
        "battery_warnings":  _chart_battery_warnings,
        "battery_over_time": _chart_battery_over_time,
    }

    results: dict[str, str] = {}
    conn = sqlite3.connect(db_path)
    try:
        for name, fn in builders.items():
            out_path = os.path.join(out_dir, CHART_FILENAMES[name])
            results[name] = fn(conn, out_path)
    finally:
        conn.close()
    return results
