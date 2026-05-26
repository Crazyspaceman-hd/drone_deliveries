# Assumptions & calibration

This document describes the assumptions the simulator runs on. It is
intentionally short, deliberately imprecise where precision would be
fake, and clearly separates two kinds of assumption:

1. **Publicly informed.** Loosely anchored to ranges that appear in
   public reporting and industry discussion of delivery operations,
   small-drone energy use, urban/suburban/rural density, and last-mile
   economics. No specific source is cited here; the values are picked
   to land in plausible ballparks, not to match any particular study.
2. **Explicitly synthetic.** Invented by this project to make the
   simulator produce comparative behaviour. These are visible knobs,
   not estimates of the real world.

The simulator's outputs are **comparative, not predictive.** Use them
to compare *scenarios* (urban vs suburban vs rural) and *levers*
(emergency-return cost, maintenance burden, delivery fee), not to
forecast anything about a real delivery network.

If you change any value in this document, also change the matching
constant in `core/scenarios.py` and rerun the suite — the BI thresholds
in `core/business_intelligence.py` are tuned to the current scenarios
and will need re-tuning if the cost model shifts substantially.

---

## 1. Publicly informed assumptions

These knobs are picked to land in plausible ranges. Public reporting
and industry discussion often place values somewhere near these
numbers; the exact values here are chosen for clean comparative
behaviour, not accuracy.

### Operational geometry

| Field (Scenario) | urban_dense | suburban_standard | rural_extended | Rationale |
|---|---:|---:|---:|---|
| `avg_trip_distance_km` | 3.0 | 6.0 | 12.0 | Public reporting often describes urban last-mile distances in single-digit km, with rural reach extending well past that. **As of Phase 14 this knob materially drives coordinate generation**: pickup/dropoff are sampled around the depot with radius ≈ `avg / 3.27`, so observed trip distances now track this value within ~1–2 km. |
| `battery_warning_threshold` (%) | 25 | 30 | 35 | Many fleet-ops discussions place battery low-alert somewhere in the 20–35% band. Rural's higher threshold reflects "need bigger margin when you're far from depot." |

### Power & energy

| Field | urban_dense | suburban_standard | rural_extended | Rationale |
|---|---:|---:|---:|---|
| `avg_kwh_per_km` | 0.08 | 0.10 | 0.13 | Industry discussions of small delivery drones commonly place per-km energy use in the rough 0.05–0.15 kWh range, with longer-range cruise designs at the upper end. The relative spread here matters more than the absolute numbers. |
| `energy_cost_per_kwh` (USD) | 0.15 | 0.15 | 0.15 | Loosely tracks U.S. residential/commercial retail electricity ranges. Held constant across scenarios because the difference between urban/rural retail rates is dwarfed by the other knobs. |

### Maintenance

| Field | urban_dense | suburban_standard | rural_extended | Rationale |
|---|---:|---:|---:|---|
| `maintenance_duration_seconds` | 180 | 240 | 360 | Many ops discussions put quick field-swap maintenance in the few-minutes range; longer for rural where parts/transport friction is higher. |
| `maintenance_cost_per_event` (USD) | 40 | 50 | 70 | Direction (rural > urban) reflects field-service-call cost discussions; absolute values are chosen so comparative analysis is readable. |

### Revenue

| Field | urban_dense | suburban_standard | rural_extended | Rationale |
|---|---:|---:|---:|---|
| `delivery_fee` (USD) | 18 | 20 | 25 | Public reporting on last-mile delivery fees varies widely; chosen so rural fees are higher (longer distance) but still don't cover the cost — which lets the BI layer surface the "rural needs >2× fee to break even" finding. |

---

## 2. Explicitly synthetic assumptions

These are project-internal knobs, picked to make the simulator produce
useful comparative behaviour. They are **not** anchored to anything
external. Treat them as exploratory rather than calibrated.

### Simulator behaviour knobs

| Field | urban_dense | suburban_standard | rural_extended | Why synthetic |
|---|---:|---:|---:|---|
| `emergency_return_chance` | 0.02 | 0.05 | 0.10 | Picked to produce visibly different abort rates per scenario. Not derived from real abort data. |
| `route_deviation_chance` | 0.10 | 0.05 | 0.02 | Picked to give urban "weaves around obstacles" texture and rural "open airspace" texture. |
| `maintenance_chance` | 0.06 | 0.08 | 0.12 | Per-trip RNG knob for non-emergency maintenance — purely to shape the maintenance density. |
| `battery_drain_multiplier` | 0.8 | 1.0 | 1.6 | Scales the simulator's per-step drain values. Suburban=1.0 is the baseline so the historical seed=42 run reproduces. |
| `telemetry_bonus_per_leg` | +2 | 0 | 0 | Extra pings per leg in dense urban environments. Not from a real telemetry specification. |
| `emergency_return_penalty` (USD) | 15 | 25 | 60 | A synthetic financial drag applied to aborted trips. Directionally reflects "rural aborts are worse" but the absolute values are invented. |
| `labor_cost_per_delivery` (USD) | 4 | 5 | 8 | Flat per-trip labour overhead. Rural slightly higher to reflect longer dispatch involvement. Invented. |
| `drone_depreciation_per_trip` (USD) | 2 | 2 | 3 | Per-trip equipment wear assumption. Invented. |

### Business-intelligence weights

The BI layer (`core/business_intelligence.py`) scores scenarios with a
hand-written weighted formula:

```
score = 50 × completion_rate
      + 30 × clip(profit_margin_pct / 100, -1..+1)
      - 40 × emergency_rate
      - 10 × maintenance_per_trip
```

With label thresholds:

```
score >= 25  → strong_candidate
score >= 10  → borderline
otherwise    → poor_candidate
```

Both the weights and the thresholds are **synthetic** — chosen so the
three built-in scenarios separate cleanly. If you change the cost
model, expect to retune them.

---

## 3. How assumptions influence outputs

- Trip distance feeds energy cost directly (`distance_km × avg_kwh_per_km × energy_cost_per_kwh`).
- Emergency-return probability feeds both the operational "aborted trip" count *and* the per-trip emergency penalty cost.
- Maintenance probability and emergency returns drive `maintenance_events_per_trip`, which drives maintenance cost and the BI scoring penalty.
- Battery drain multiplier and warning threshold drive the `battery_warning` event density, which drives the operational story but does **not** currently feed into the cost model.
- BI scoring weights determine rankings but not the underlying economics. Changing them changes which scenario looks best, not which scenario actually loses the least money.

---

## 4. What is intentionally not modelled

These would be next-step calibration work. None are in this project today:

- weather / wind degrading battery
- regulatory routing (FAA flight restrictions)
- traffic / pedestrian density beyond a simple "deviation chance"
- charging-station availability
- fleet capital cost / amortisation schedules
- demand modelling (orders just exist when the simulator creates them)
- multi-depot routing
- real geographic data (we use bounded random points around a single depot)

Adding any of these would push the project from "transparent exploratory
sim" toward "realism theatre." The current design favours the former.
