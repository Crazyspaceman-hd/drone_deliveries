"""
run_transforms.py — recompute derived analytical tables.

Examples::

    python run_transforms.py                           # default pipeline,
                                                       # default domain (retail_package)
                                                       # default scale  (pilot_program)
    python run_transforms.py --run-id <id>             # scope to one simulation run
    python run_transforms.py --transform economics     # only the economics step

    # Phase 22 backfill + Phase 23 additions: explicit overlay choices.
    python run_transforms.py --delivery-domain food_delivery
    python run_transforms.py --scale-model urban_dense_fleet
    python run_transforms.py --all-delivery-domains
    python run_transforms.py --all-scale-models

CLI semantics
─────────────
* Without any overlay flag the default pipeline runs once with each
  transform's documented default (economics → retail_package,
  scale → pilot_program).
* --delivery-domain / --scale-model bind one overlay value; combinable.
* --all-delivery-domains / --all-scale-models loop over the relevant
  registry and run the matching transform once per profile.  They
  implicitly restrict to that transform module (no point recomputing
  hybrid four times for four scale models).
"""

import argparse
import os
import sys

from transforms import economics as economics_module
from transforms import scale as scale_module
from transforms.runner import pipeline_names, run_for_all_runs, run_pipeline


# Lazy imports for the registries so the CLI doesn't pay their cost on
# every invocation that doesn't use them.
def _list_delivery_domains() -> list[str]:
    from core.delivery_domains import list_domains
    return list_domains()


def _list_scale_models() -> list[str]:
    from core.scale_models import list_scale_models
    return list_scale_models()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recompute derived analytical state from raw simulator events."
    )
    parser.add_argument("--db",        default="data/delivery_system.sqlite")
    parser.add_argument("--run-id",    default=None,
                        help="Limit transforms to one simulation run.")
    parser.add_argument("--all-runs",  action="store_true",
                        help="Run the transform pipeline once per simulation_runs row.")
    parser.add_argument("--transform", default=None,
                        choices=pipeline_names(),
                        help="Restrict to a single transform (default: all).")

    # Phase 22/23: overlay flags.  --delivery-domain backfills Phase 22's
    # CLI gap; --scale-model is new in Phase 23.  The --all-* variants
    # implicitly restrict to the transform that owns that overlay.
    parser.add_argument("--delivery-domain",     default=None,
                        help="Override delivery domain for the economics transform.")
    parser.add_argument("--all-delivery-domains", action="store_true",
                        help="Run the economics transform once per registered domain.")
    parser.add_argument("--scale-model",          default=None,
                        help="Override scale model for the scale transform.")
    parser.add_argument("--all-scale-models",     action="store_true",
                        help="Run the scale transform once per registered scale model.")

    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 2

    # ── overlay sweeps: --all-delivery-domains, --all-scale-models ──────
    # These take precedence over the default pipeline because they're
    # always single-transform fans.
    if args.all_delivery_domains:
        results = _sweep_overlays(
            args.db, args.run_id, "economics",
            kwarg_name = "delivery_domain",
            values     = _list_delivery_domains(),
        )
    elif args.all_scale_models:
        results = _sweep_overlays(
            args.db, args.run_id, "scale",
            kwarg_name = "scale_model",
            values     = _list_scale_models(),
        )
    elif args.delivery_domain is not None or args.scale_model is not None:
        # Single overlay value(s).  We invoke the transform module(s)
        # directly so we can pass the kwarg — the generic runner doesn't
        # know about overlay-specific arguments.
        results = []
        if args.delivery_domain is not None:
            results.append(economics_module.run(
                args.db, run_id=args.run_id,
                delivery_domain=args.delivery_domain,
            ))
        if args.scale_model is not None:
            results.append(scale_module.run(
                args.db, run_id=args.run_id,
                scale_model=args.scale_model,
            ))
    elif args.run_id:
        results = run_pipeline(args.db, run_id=args.run_id, only=args.transform)
    elif args.all_runs:
        results = run_for_all_runs(args.db, only=args.transform)
    else:
        # Default: one pipeline pass with no run scope.
        results = run_pipeline(args.db, run_id=None, only=args.transform)

    if not results:
        print("(no transforms ran — check --run-id or that simulation_runs has rows)")
        return 0

    print(f"Ran {len(results)} transform(s):\n")
    header = (f"{'transform':<12} {'version':<14} {'rows':>6}  "
              f"{'source_run':<10}  {'overlay':<22} transform_run_id")
    print(header)
    print("-" * len(header))
    for r in results:
        src = (r.get('source_run_id') or '-')[:8]
        overlay = (r.get('delivery_domain')
                   or r.get('scale_model')
                   or '-')[:22]
        print(f"{r['transform_name']:<12} {r['transform_version']:<14} "
              f"{r['rows_updated']:>6}  {src:<10}  {overlay:<22} "
              f"{r['transform_run_id']}")
    print()
    return 0


def _sweep_overlays(
    db_path: str, run_id: str | None, transform_name: str,
    *, kwarg_name: str, values: list[str],
) -> list[dict]:
    """Loop one transform over every overlay value in a registry."""
    module = economics_module if transform_name == "economics" else scale_module
    out: list[dict] = []
    for value in values:
        out.append(module.run(db_path, run_id=run_id, **{kwarg_name: value}))
    return out


if __name__ == "__main__":
    sys.exit(main())
