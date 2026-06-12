# Release checklist — v1.0-portfolio

| Item | Status | Notes |
|---|---|---|
| README polished (recruiter-first) | ☑ | v1.0 banner, cautious conclusion, 5-min review, Key findings (32/33), v1 scope, future v2 |
| Portfolio summary complete | ☑ | `docs/portfolio_summary.md` — service-mix + what-if sections added |
| Final showcase chart generated | ☑ | `docs/img/viability_by_capacity_and_domain.png` (primary) + `service_mix_profit_by_volume.png` (supporting) |
| Screenshots added | ◻ | `docs/screenshots/README.md` capture guide present; UI PNGs require a manual capture pass (see note) |
| Demo commands verified | ☑ | `scripts/run_demo.sh` mirrors the reference workflow |
| Validation passes | ☑ | `python run_validation.py` clean |
| Fast tests pass | ☑ | `pytest -m "not slow"` green |
| Full tests pass | ☑ | `pytest` green |
| Frontend builds | ☑ | `cd frontend && npm run build` clean |
| Limitations documented | ☑ | README "Known limitations" + per-module caveats |
| Future work documented | ☑ | README "Future v2 direction" — real-data ingestion |
| GitHub About updated manually | ◻ | Set to: *Event-driven analytics pipeline using synthetic drone delivery data to evaluate last-mile delivery economics.* (manual, on GitHub) |
| Release tag created | ◻ | Recommended: `v1.0-portfolio` (manual `git tag`) |

## Verified headline numbers (current local DB)

- Operator sweep at pilot native productivity (8 deliveries/drone/day):
  `operator_to_drone_ratio` 0.60 → 0.20 moves the margin **−$15.89 → −$3.89**
  per delivery — improves but does not reach break-even.
- Service mixes at `pilot_capacity`, 650 deliveries/day: best
  `pharmacy_courier` **−$9.82**, worst `platform_mixed_local` **−$11.94**;
  every listed mix beats its weakest component, all stay negative.

## Manual steps remaining (not automatable here)

1. Capture the five UI screenshots per `docs/screenshots/README.md`.
2. Set the GitHub **About** text.
3. `git tag v1.0-portfolio && git push --tags`.
