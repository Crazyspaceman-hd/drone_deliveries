# Workbench screenshots

These are reviewer-facing captures of the running React workbench. They
are **not auto-generated** — capture them once from a populated workbench
and commit the PNGs alongside this file.

## How to capture

```bash
bash scripts/run_demo.sh      # populate the DB + charts
python workbench.py           # opens http://localhost:5173
```

Then capture each view at a consistent window width (~1280px) and save
with these exact names so the README/portfolio docs resolve:

| File | Workbench location |
|---|---|
| `workbench_overview.png` | Overview page (`/`) |
| `main_finding.png` | Main finding page (`/finding`) |
| `viability_grid_what_if.png` | Experiments page after running a capacity what-if, then the recoloured grid on `/finding` |
| `service_mix_analysis.png` | Domain & Scale → "Service-mix analysis" section |
| `final_showcase_chart.png` | The viability grid chart, or `outputs/charts/viability_by_capacity_and_domain.png` |

## Already-published static charts

Two chart artifacts are committed under [`docs/img/`](../img/) and do not
need manual capture — `run_visualizations.py` republishes them on every
run:

- `viability_by_capacity_and_domain.png` — the showcase chart.
- `service_mix_profit_by_volume.png` — Phase 33 service-mix curves.

> Note: UI screenshots require a human (or a headless browser) to capture
> the live React app; they are intentionally left as a manual step.
