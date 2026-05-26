"""
core/duckdb_analytics.py

Lightweight DuckDB layer over the per-run Parquet exports.

Architecture
─────────────
  SQLite      = operational system of record
  Parquet     = analytical export layer    (one file per table per run)
  DuckDB      = analytical query engine    (this module)

DuckDB is used in-process — no server, no persistent file.  We glob the
per-run Parquet directories and union them into virtual tables, which
keeps cross-run analytics trivially expressible in plain SQL.

Public surface
───────────────
  discover_run_parquet_dirs(base_dir)
      Return the list of per-run Parquet directories present on disk.

  open_duckdb_for_runs(parquet_dirs)
      Open an in-memory DuckDB connection with four views:
        delivery_events, trips, orders, simulation_runs
      Each view is a UNION ALL over the matching .parquet file across
      the provided directories.

  run_duckdb_query(parquet_dirs, sql)
      Convenience wrapper: open, execute, fetch all rows + headers, close.

  load_sql_file(path)
      Read a .sql file and run it.

  generate_duckdb_summary(parquet_dirs, sql_dir="analytics/duckdb")
      Run every .sql file under sql_dir and return a {name: rows} dict.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional


# Tables we expect each per-run Parquet export to contain.
_EXPECTED_TABLES = ("delivery_events", "trips", "orders", "simulation_runs")


def _require_duckdb():
    try:
        import duckdb       # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "DuckDB analytics require the `duckdb` package. "
            "Install via `pip install duckdb` (or `pip install -r requirements.txt`)."
        ) from exc


def discover_run_parquet_dirs(base_dir: str = "outputs/runs") -> list[str]:
    """Return ``run_id=*`` subdirs that contain a ``parquet/`` folder."""
    base = Path(base_dir)
    if not base.exists():
        return []
    found: list[str] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        pq = child / "parquet"
        if pq.is_dir() and any(pq.glob("*.parquet")):
            found.append(str(pq))
    return found


def open_duckdb_for_runs(parquet_dirs: Iterable[str]):
    """Open an in-memory DuckDB and create one view per expected table."""
    _require_duckdb()
    import duckdb
    dirs = [d for d in parquet_dirs if Path(d).is_dir()]
    if not dirs:
        raise FileNotFoundError(
            "No parquet directories found. Run an export first "
            "(e.g. `python run_scenarios.py --export-parquet`)."
        )

    con = duckdb.connect(database=":memory:")
    for table in _EXPECTED_TABLES:
        # Use a UNION ALL of read_parquet() calls — DuckDB will skip files
        # that exist in some dirs but not others.  Quoting the path keeps
        # Windows backslashes safe.
        present_files = [
            str(Path(d) / f"{table}.parquet")
            for d in dirs
            if (Path(d) / f"{table}.parquet").exists()
        ]
        if not present_files:
            # Materialise an empty view so SELECTs don't error.  The empty
            # SELECT inherits no columns; downstream queries that hit this
            # table will fail informatively.
            con.execute(f"CREATE VIEW {table} AS SELECT NULL WHERE 1=0")
            continue
        # Build the per-file UNION ALL.  We use read_parquet on each file
        # so DuckDB picks up the schema from the file itself.
        unioned = " UNION ALL ".join(
            f"SELECT * FROM read_parquet('{p}')" for p in present_files
        )
        con.execute(f"CREATE VIEW {table} AS {unioned}")
    return con


def open_duckdb_for_sqlite(db_path: str):
    """Attach the operational SQLite DB to a fresh in-memory DuckDB.

    Phase 20: DuckDB can query SQLite directly via the ``sqlite_scanner``
    extension.  Parquet exports are no longer required for cross-layer
    analytical work — they remain useful for portability, but you can
    skip them entirely and still get DuckDB's SQL features.

    The same view names (``delivery_events``, ``trips``, ``orders``,
    ``simulation_runs``) are exposed so callers don't have to care
    whether the underlying storage is SQLite or Parquet.
    """
    _require_duckdb()
    import duckdb
    if not Path(db_path).exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    con = duckdb.connect(database=":memory:")
    # Best-effort: install + load the sqlite_scanner extension.  In modern
    # DuckDB releases this is bundled and ATTACH 'file.sqlite' (TYPE SQLITE)
    # works without an explicit INSTALL/LOAD.
    try:
        con.execute("INSTALL sqlite_scanner;")
        con.execute("LOAD sqlite_scanner;")
    except Exception:
        pass
    con.execute(f"ATTACH '{db_path}' AS sqlite_src (TYPE SQLITE);")
    for table in _EXPECTED_TABLES:
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM sqlite_src.{table}")
    return con


def run_duckdb_query(parquet_dirs: Iterable[str], sql: str) -> tuple[list[str], list[tuple]]:
    """Execute one SQL statement and return (headers, rows)."""
    con = open_duckdb_for_runs(parquet_dirs)
    try:
        cur = con.execute(sql)
        headers = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    finally:
        con.close()
    return headers, rows


def load_sql_file(path: str) -> str:
    """Read a SQL file and return its text (UTF-8)."""
    return Path(path).read_text(encoding="utf-8")


def generate_duckdb_summary(
    parquet_dirs: Iterable[str],
    sql_dir: str = "analytics/duckdb",
) -> dict[str, dict]:
    """Run every .sql file in ``sql_dir`` and return {name: {headers, rows}}.

    Keys are the file's stem (e.g. ``cross_run_profitability``) so callers
    can render or compare without parsing paths.
    """
    base = Path(sql_dir)
    if not base.is_dir():
        return {}
    out: dict[str, dict] = {}
    con = open_duckdb_for_runs(list(parquet_dirs))
    try:
        for sql_path in sorted(base.glob("*.sql")):
            sql = sql_path.read_text(encoding="utf-8")
            cur = con.execute(sql)
            headers = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            out[sql_path.stem] = {
                "path":    str(sql_path),
                "headers": headers,
                "rows":    rows,
            }
    finally:
        con.close()
    return out
