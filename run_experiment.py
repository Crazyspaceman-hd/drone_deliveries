#!/usr/bin/env python
"""
run_experiment.py — Phase 24 CLI for experiment orchestration.

Usage examples
──────────────
Run a registered experiment against all sim runs in the default DB:

    python run_experiment.py --name domain_sweep

Run against a specific DB and a subset of sim runs:

    python run_experiment.py --name scale_sweep --db data/my_run.sqlite

Restrict to specific simulation run IDs:

    python run_experiment.py --name full_grid \\
        --db data/my_run.sqlite \\
        --run-ids <run_id_1> <run_id_2>

List all registered experiment names:

    python run_experiment.py --list

Output
──────
Prints the experiment_run_id on completion (or a failure summary).
No interactive output beyond that — designed for scripted pipelines.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_experiment",
        description="Execute a registered experiment sweep.",
    )
    parser.add_argument(
        "--name", "-n",
        help="Registered experiment name (see --list for options).",
    )
    parser.add_argument(
        "--db",
        default="data/delivery_system.sqlite",
        help="Path to the SQLite database.  Default: data/delivery_system.sqlite",
    )
    parser.add_argument(
        "--run-ids",
        nargs="*",
        metavar="RUN_ID",
        help="One or more simulation run IDs to sweep.  "
             "Omit to use all runs in the DB (or as defined in the experiment).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print all registered experiment names and exit.",
    )
    # Phase 31: ad-hoc parameter sweep without registering an experiment.
    parser.add_argument(
        "--sweep",
        metavar="DIMENSION.PARAMETER",
        help="Ad-hoc parameter sweep, e.g. "
             "delivery_domain.saturation_volume_per_day.  "
             "Requires --base and --values.  Mutually exclusive with --name.",
    )
    parser.add_argument(
        "--base",
        help="Registered entry to vary (with --sweep), e.g. food_delivery.",
    )
    parser.add_argument(
        "--values",
        help="Comma-separated values to sweep (with --sweep), e.g. 1500,2500,4000.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=[],
        metavar="SCENARIO",
        help="Optional scenario filter for --sweep mode.",
    )
    args = parser.parse_args(argv)

    import dataclasses
    from datetime import datetime, timezone

    from core.experiments import (
        Experiment, ExperimentDefinition, ParameterSweep,
        get_experiment, list_experiments,
    )

    if args.list:
        names = list_experiments()
        if names:
            print("Registered experiments:")
            for n in names:
                print(f"  {n}")
        else:
            print("No experiments registered.")
        return 0

    if args.sweep and args.name:
        parser.error("--sweep and --name are mutually exclusive")

    if args.sweep:
        if not args.base or not args.values:
            parser.error("--sweep requires --base and --values")
        if "." not in args.sweep:
            parser.error("--sweep must be DIMENSION.PARAMETER, "
                         "e.g. delivery_domain.saturation_volume_per_day")
        dimension, parameter = args.sweep.split(".", 1)
        # Reuse the synthetic-name coercion so CLI values match what the
        # resolver will parse back out of the snapshot names.
        from core.parameter_sweeps import _coerce
        values = [_coerce(v.strip()) for v in args.values.split(",") if v.strip()]
        sweep = ParameterSweep(
            dimension = dimension,
            base_name = args.base,
            parameter = parameter,
            values    = values,
        )
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # Capacity base belongs on the capacity axis (read-side), NOT in
        # delivery_domains — only a delivery-domain sweep gets its base
        # included as a baseline domain row.
        domains = [args.base] if dimension == "delivery_domain" else ["retail_package"]
        defn = ExperimentDefinition(
            name             = f"_adhoc_{ts}",
            run_ids          = list(args.run_ids or []),
            scenarios        = list(args.scenarios),
            economic_models  = ["suburban_standard"],
            delivery_domains = domains,
            scale_models     = ["pilot_program"],
            parameter_sweeps = [sweep],
        )
    else:
        if not args.name:
            parser.error("--name or --sweep is required (or use --list)")
        defn = get_experiment(args.name)
        # Override run_ids if supplied — replace() preserves every other
        # field including parameter_sweeps.
        if args.run_ids:
            defn = dataclasses.replace(defn, run_ids=list(args.run_ids))

    exp    = Experiment(defn, args.db)
    result = exp.run()

    if result["status"] == "completed":
        print(result["experiment_run_id"])
        return 0
    else:
        print(f"FAILED: {result.get('error', 'unknown error')}", file=sys.stderr)
        print(result["experiment_run_id"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
