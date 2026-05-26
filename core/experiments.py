"""
core/experiments.py

Experiment orchestration layer (Phase 24).

What an experiment IS
──────────────────────
An experiment is a named Cartesian sweep of analytical knobs over one or
more existing simulation runs.  It calls the economics and scale transforms
for each (run_id × economic_model × delivery_domain × scale_model) combination
and tags every produced ``transformation_runs`` row with its
``experiment_run_id`` for lineage.

What an experiment IS NOT
──────────────────────────
- It is not a simulator.  ``ExperimentDefinition`` carries no seed, no
  ``n_trips``, no ``n_drones``.  Those fields live on the sim run that
  feeds the experiment.
- It does not call ``run_pipeline()``.  It calls ``transforms/economics.py``
  and ``transforms/scale.py`` individually, in the right order, chaining the
  economics ``transform_run_id`` into the scale call's
  ``source_snapshot_run_id``.

Layering rule reminder
───────────────────────
    Scenario           = operational knobs (Phase 9)
    EconomicModel      = unit prices (Phase 20)
    delivery_domain    = demand-side characteristics (Phase 22)
    scale_model        = fleet-wide overhead amortization (Phase 23)
    Experiment         = named Cartesian sweep over the above (Phase 24)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from core.delivery_domains import get_domain, list_domains
from core.economic_models import get_economic_model, list_economic_models
from core.scale_models import get_scale_model, list_scale_models


# ─────────────────────────────────────────────────────────────────────────────
# ExperimentDefinition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExperimentDefinition:
    """Immutable description of an experiment.

    Dimension fields
    ─────────────────
    All four analytical-knob fields are plural lists for shape symmetry.
    An empty list on any field means "use all registered values" at
    experiment runtime.  Passing a scalar raises ``TypeError`` (enforced
    in ``__post_init__``).

    run_ids
        Source simulation run IDs to sweep.  Empty = pull all sim runs
        from the database at runtime.

    scenarios
        Scenario-name filter applied to run_ids: only sim runs that
        contain trips with at least one of these scenario_names will be
        included.  Empty = no filter (all sim runs).

    economic_models
        Scenario names used as EconomicModel identifiers.  Each name
        resolves to its default EconomicModel via
        ``core.economic_models.get_economic_model(name)``.
        Empty = all registered models.

    delivery_domains
        Delivery-domain names passed to the economics transform as the
        demand-side overlay.  Empty = all registered domains.

    scale_models
        Scale-model names passed to the scale transform.
        Empty = all registered scale models.
    """

    name:             str
    run_ids:          list   # list[str]
    scenarios:        list   # list[str]
    economic_models:  list   # list[str]
    delivery_domains: list   # list[str]
    scale_models:     list   # list[str]

    def __post_init__(self) -> None:
        for field in ("run_ids", "scenarios", "economic_models",
                      "delivery_domains", "scale_models"):
            val = getattr(self, field)
            if not isinstance(val, list):
                raise TypeError(
                    f"ExperimentDefinition.{field} must be a list, "
                    f"got {type(val).__name__!r}"
                )

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Experiment
# ─────────────────────────────────────────────────────────────────────────────

class Experiment:
    """Binds an ``ExperimentDefinition`` to a database and executes sweeps.

    Typical usage::

        exp = Experiment(get_experiment("scale_sweep"), db_path)
        result = exp.run()
        summary = exp.compute_summary()
    """

    def __init__(self, definition: ExperimentDefinition, db_path: str) -> None:
        self._defn   = definition
        self._db     = db_path
        self._last_run_id: Optional[str] = None

    # ── Public: run ───────────────────────────────────────────────────────────

    def run(self) -> dict:
        """Execute the experiment sweep.

        For each (run_id × economic_model × delivery_domain × scale_model)
        in the Cartesian product:
          1. Calls ``economics.run()`` tagged with this experiment's id.
          2. Chains the resulting transform_run_id into ``scale.run()``
             so every scale snapshot is traceable back to its exact
             economics source.

        Returns a summary dict with ``experiment_run_id`` and ``status``.
        Always returns (never raises) — failures are captured in the
        ``experiment_runs`` table with ``status='failed'``.
        """
        # Lazy imports to keep module-level imports light.
        from transforms import economics as econ_mod
        from transforms import scale as scale_mod

        exp_id     = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        self._write_exp_row(exp_id, "running", started_at, None, None)

        try:
            run_ids      = self._resolve_run_ids()
            model_names  = self._defn.economic_models  or list_economic_models()
            domain_names = self._defn.delivery_domains or list_domains()
            scale_names  = self._defn.scale_models     or list_scale_models()

            # Validate all dimension values BEFORE running any transforms so a
            # typo in one name causes an immediate, clean failure rather than a
            # partial write.
            for m in model_names:
                get_economic_model(m)     # raises KeyError if unknown
            for d in domain_names:
                get_domain(d)             # raises KeyError if unknown
            for s in scale_names:
                get_scale_model(s)        # raises KeyError if unknown

            combinations = 0
            for rid in run_ids:
                for model_name in model_names:
                    model = get_economic_model(model_name)
                    for domain_name in domain_names:
                        econ_result = econ_mod.run(
                            self._db,
                            run_id          = rid,
                            model           = model,
                            delivery_domain = domain_name,
                            experiment_run_id = exp_id,
                        )
                        econ_tx_id = econ_result["transform_run_id"]

                        for scale_name in scale_names:
                            scale_mod.run(
                                self._db,
                                run_id                 = rid,
                                scale_model            = scale_name,
                                source_snapshot_run_id = econ_tx_id,
                                experiment_run_id      = exp_id,
                            )
                            combinations += 1

            completed_at = datetime.now(timezone.utc).isoformat()
            self._update_exp_row(exp_id, "completed", completed_at, None)
            self._last_run_id = exp_id
            return {
                "experiment_run_id": exp_id,
                "status":            "completed",
                "combinations":      combinations,
            }

        except Exception as exc:
            completed_at = datetime.now(timezone.utc).isoformat()
            error_msg    = f"{type(exc).__name__}: {exc}"
            self._update_exp_row(exp_id, "failed", completed_at, error_msg)
            self._last_run_id = exp_id
            return {
                "experiment_run_id": exp_id,
                "status":            "failed",
                "error":             error_msg,
            }

    # ── Public: compute_summary ───────────────────────────────────────────────

    def compute_summary(self) -> dict:
        """Aggregate snapshot rows tagged with the most recent run.

        Returns per-(scenario × delivery_domain × scale_model) averages:
        effective_profit, overhead, revenue, and break-even rate.

        Pure read — no writes.
        """
        if self._last_run_id is None:
            raise RuntimeError(
                "compute_summary() called before run(); call run() first."
            )
        return Experiment.compute_summary_for(self._db, self._last_run_id)

    @staticmethod
    def compute_summary_for(db_path: str, experiment_run_id: str) -> dict:
        """Compute summary for any ``experiment_run_id`` without an
        ``Experiment`` instance.  Used by the API endpoint."""
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                """
                SELECT t.scenario_name,
                       e.domain_name,
                       s.scale_model_name,
                       AVG(s.effective_profit)              AS avg_effective_profit,
                       AVG(s.amortized_overhead_per_trip)   AS avg_overhead,
                       AVG(e.estimated_revenue)             AS avg_revenue,
                       CAST(
                           SUM(CASE WHEN s.effective_profit > 0 THEN 1.0 ELSE 0.0 END)
                           AS REAL
                       ) / COUNT(*)                         AS break_even_rate,
                       COUNT(*)                             AS trip_count
                  FROM trip_scale_snapshots    s
                  JOIN transformation_runs     tx
                       ON  tx.transform_run_id = s.transform_run_id
                  JOIN trip_economics_snapshots e
                       ON  e.transform_run_id  = s.source_snapshot_run_id
                       AND e.trip_id           = s.trip_id
                  JOIN trips t ON t.trip_id    = s.trip_id
                 WHERE tx.experiment_run_id    = ?
                 GROUP BY t.scenario_name, e.domain_name, s.scale_model_name
                 ORDER BY t.scenario_name, e.domain_name, s.scale_model_name
                """,
                (experiment_run_id,),
            ).fetchall()
        finally:
            conn.close()

        return {
            "experiment_run_id": experiment_run_id,
            "profiles": [
                {
                    "scenario_name":        r[0],
                    "domain_name":          r[1],
                    "scale_model_name":     r[2],
                    "avg_effective_profit": round(float(r[3] or 0), 2),
                    "avg_overhead":         round(float(r[4] or 0), 2),
                    "avg_revenue":          round(float(r[5] or 0), 2),
                    "break_even_rate":      round(float(r[6] or 0), 4),
                    "trip_count":           int(r[7] or 0),
                }
                for r in rows
            ],
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _resolve_run_ids(self) -> list[str]:
        """Expand run_ids (with optional scenario filter) against the DB."""
        conn = sqlite3.connect(self._db)
        try:
            if self._defn.run_ids:
                return list(self._defn.run_ids)

            if self._defn.scenarios:
                # Only include sim runs that have at least one trip with one
                # of the specified scenario_names.
                ph = ",".join("?" * len(self._defn.scenarios))
                rows = conn.execute(
                    f"SELECT DISTINCT run_id FROM trips "
                    f" WHERE scenario_name IN ({ph}) AND run_id IS NOT NULL",
                    tuple(self._defn.scenarios),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT run_id FROM simulation_runs ORDER BY created_at ASC"
                ).fetchall()

            return [r[0] for r in rows]
        finally:
            conn.close()

    def _write_exp_row(
        self, exp_id: str, status: str,
        started_at: Optional[str], completed_at: Optional[str],
        error: Optional[str],
    ) -> None:
        defn_json = json.dumps(self._defn.to_dict(), separators=(",", ":"),
                               sort_keys=True)
        conn = sqlite3.connect(self._db)
        try:
            conn.execute(
                """
                INSERT INTO experiment_runs
                    (experiment_run_id, experiment_name, definition_json,
                     status, started_at, completed_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (exp_id, self._defn.name, defn_json, status,
                 started_at, completed_at, error),
            )
            conn.commit()
        finally:
            conn.close()

    def _update_exp_row(
        self, exp_id: str, status: str,
        completed_at: str, error: Optional[str],
    ) -> None:
        conn = sqlite3.connect(self._db)
        try:
            conn.execute(
                """
                UPDATE experiment_runs
                   SET status = ?, completed_at = ?, error = ?
                 WHERE experiment_run_id = ?
                """,
                (status, completed_at, error, exp_id),
            )
            conn.commit()
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Built-in experiment registry
# ─────────────────────────────────────────────────────────────────────────────

_EXPERIMENT_REGISTRY: dict[str, ExperimentDefinition] = {}


def register_experiment(defn: ExperimentDefinition) -> None:
    """Add a definition to the registry.  Overwrites on name collision."""
    _EXPERIMENT_REGISTRY[defn.name] = defn


def get_experiment(name: str) -> ExperimentDefinition:
    """Look up a registered experiment by name.  Raises ``KeyError``."""
    try:
        return _EXPERIMENT_REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_EXPERIMENT_REGISTRY.keys()))
        raise KeyError(
            f"unknown experiment {name!r}; registered: {known}"
        ) from None


def list_experiments() -> list[str]:
    """Sorted list of all registered experiment names."""
    return sorted(_EXPERIMENT_REGISTRY.keys())


# ── Three built-in definitions ────────────────────────────────────────────────
# Empty lists mean "all registered values" — they expand at run time.
# run_ids is also empty = all sim runs currently in the target DB.

register_experiment(ExperimentDefinition(
    name             = "domain_sweep",
    run_ids          = [],
    scenarios        = [],
    # Hold the economic model constant (default scenario assumptions) and
    # sweep all four delivery domains.  Use pilot_program scale so domain
    # differences aren't blurred by fleet-overhead variance.
    economic_models  = ["suburban_standard"],
    delivery_domains = [],        # → all 4 domains
    scale_models     = ["pilot_program"],
))

register_experiment(ExperimentDefinition(
    name             = "scale_sweep",
    run_ids          = [],
    scenarios        = [],
    # Hold domain and model constant; sweep all four scale tiers.
    # retail_package is the pre-Phase-22 default domain — keeps results
    # comparable to prior phases.
    economic_models  = ["suburban_standard"],
    delivery_domains = ["retail_package"],
    scale_models     = [],        # → all 4 scale models
))

register_experiment(ExperimentDefinition(
    name             = "full_grid",
    run_ids          = [],
    scenarios        = [],
    # Full Cartesian product — expands to (all models × all domains × all scales).
    economic_models  = [],
    delivery_domains = [],
    scale_models     = [],
))
