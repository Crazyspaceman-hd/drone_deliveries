#!/usr/bin/env bash
# scripts/run_demo.sh — reference demo workflow for the drone-delivery
# analytics pipeline (v1.0-portfolio).
#
# Seeds a deterministic DB, runs every overlay transform, fires the two
# built-in what-if experiments, renders charts, and validates.  After
# this finishes, `python workbench.py` shows a fully-populated workbench.
#
# Usage:  bash scripts/run_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DB=data/delivery_system.sqlite

echo "==> 1/6  seed simulation (3 scenarios x 100 trips, seed 42)"
python run_scenarios.py --scenarios urban_dense suburban_standard rural_extended --trips 100 --seed 42

echo "==> 2/6  run transforms (economics, scale, domains)"
python run_transforms.py --all-runs
python run_transforms.py --all-runs --all-delivery-domains
python run_transforms.py --all-runs --all-scale-models

echo "==> 3/6  built-in what-if experiments"
python run_experiment.py --name food_saturation_sensitivity
python run_experiment.py --name pilot_operator_ratio_sensitivity

echo "==> 4/6  render charts (publishes showcase charts to docs/img/)"
python run_visualizations.py --db "$DB" --out outputs/charts

echo "==> 5/6  validation"
python run_validation.py

echo "==> 6/6  done.  Launch the workbench with:"
echo "         python workbench.py"
