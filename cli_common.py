"""
cli_common.py — shared helpers for the ``run_*.py`` command-line entry points.

Every runner used to repeat the same three things: a ``--db`` flag defaulting
to the project SQLite path, a "does the database exist?" guard that prints to
stderr and exits 2, and an auto-width table printer.  They live here now so the
runners only carry their own logic.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from typing import Sequence

DEFAULT_DB = "data/delivery_system.sqlite"


def add_db_arg(parser, *, help: str = "Path to the SQLite database.") -> None:
    """Register the standard ``--db`` argument on an argparse parser."""
    parser.add_argument("--db", default=DEFAULT_DB, help=help)


def require_db(db_path: str) -> bool:
    """Return True if *db_path* exists; otherwise print to stderr and return False.

    Call sites keep their own exit code, e.g.::

        if not require_db(args.db):
            return 2
    """
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}", file=sys.stderr)
        return False
    return True


def print_table(headers: Sequence[str], rows: Sequence[Sequence]) -> None:
    """Print *rows* under *headers* as a left-aligned, auto-width table."""
    if not rows:
        print("  (no rows)")
        return
    str_rows = [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in str_rows)) for i, h in enumerate(headers)]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in str_rows:
        print(fmt.format(*r))
