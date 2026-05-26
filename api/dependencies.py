"""Common dependencies for the API layer.

The DB path is configurable via the ``DRONE_API_DB`` environment variable;
otherwise it falls back to the repo default.  Tests inject paths via the
same env var.
"""

import os
from pathlib import Path

DEFAULT_DB_PATH = "data/delivery_system.sqlite"


def get_db_path() -> str:
    return os.environ.get("DRONE_API_DB", DEFAULT_DB_PATH)


def get_charts_dir() -> str:
    return os.environ.get("DRONE_API_CHARTS_DIR", "outputs/charts")


def require_db() -> str:
    path = get_db_path()
    if not Path(path).exists():
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=(f"database not found at {path}; run a simulation first "
                    f"(e.g. `python run_simulation.py --reset --seed 42`)"),
        )
    return path
