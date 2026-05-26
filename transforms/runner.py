"""
transforms/runner.py

Orchestrates the transform pipeline.

Phase 20: hard-coded ``PIPELINE = ("economics", "hybrid")``.
Phase 21: declarative ordering via each module's ``RUN_ORDER`` constant.
The runner imports every ``transforms/<name>.py`` that exposes both a
``run(db_path, *, run_id=...)`` callable and a ``RUN_ORDER`` integer, and
executes them sorted by that integer.  Adding a new transform = adding a
new module; no edits here required.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable, Optional

import transforms                # the package itself, used for iter_modules
from transforms.runs import list_source_run_ids


# Modules that aren't actual transforms.  Anything else under transforms/
# that exposes RUN_ORDER + run() gets auto-discovered.
_EXCLUDE = {"runs", "runner"}


def _discover() -> list[tuple[int, str, Callable[..., Any]]]:
    """Return [(run_order, name, run_fn), …] sorted ascending."""
    out: list[tuple[int, str, Callable[..., Any]]] = []
    for info in pkgutil.iter_modules(transforms.__path__):
        if info.name in _EXCLUDE:
            continue
        mod = importlib.import_module(f"transforms.{info.name}")
        run_fn    = getattr(mod, "run", None)
        run_order = getattr(mod, "RUN_ORDER", None)
        if callable(run_fn) and isinstance(run_order, int):
            name = getattr(mod, "TRANSFORM_NAME", info.name)
            out.append((run_order, name, run_fn))
    out.sort(key=lambda t: t[0])
    return out


# Computed once at import time.  Stable across the process lifetime; if you
# add a new transform you'll need to restart the interpreter — same as
# Python's normal import semantics.
_PIPELINE: list[tuple[int, str, Callable[..., Any]]] = _discover()


def pipeline_names() -> list[str]:
    """Names of every transform the runner will execute, in order."""
    return [name for _ro, name, _fn in _PIPELINE]


def run_pipeline(
    db_path: str, run_id: Optional[str] = None, only: Optional[str] = None,
) -> list[dict]:
    """Run the discovered pipeline against one source run (or globally)."""
    results: list[dict] = []
    for _ro, name, run_fn in _PIPELINE:
        if only is not None and name != only:
            continue
        results.append(run_fn(db_path, run_id=run_id))
    return results


def run_for_all_runs(db_path: str, only: Optional[str] = None) -> list[dict]:
    out: list[dict] = []
    for rid in list_source_run_ids(db_path):
        out.extend(run_pipeline(db_path, run_id=rid, only=only))
    return out
