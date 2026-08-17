# Overhead cost-model research

This document anchors the **overhead / capacity cost parameters** —
the ones in [`core/capacity_models.py`](../core/capacity_models.py) and
[`core/scale_models.py`](../core/scale_models.py) — to public figures,
and audits whether the numbers are internally consistent with each
other.

It exists because those two registries grew as analytical knobs:
plausible-looking, but never checked against real-world ranges, and
never checked against *each other*. The goal here is the same as
[`assumptions.md`](assumptions.md): keep the model **comparative, not
predictive**, but make each number defensible and make the
relationships between numbers honest.

> **Still synthetic.** Nothing below turns this into a forecast. Public
> figures for drone-delivery economics are early, thin, and operator-
> reported. We use them to pin each knob to a *defensible range and the
> right ordering*, not to claim accuracy. Where a value is genuinely
> invented (platform/software floors), this document says so.

---

## TL;DR — what the research says about each knob

| Parameter | Current value(s) | Public anchor | Verdict |
|---|---|---|---|
| `operator_to_drone_ratio` | 0.50 / 0.15 / 0.08 (1:2, 1:6.7, 1:12.5) | Part 108 NPRM: 1:5 (Level-2 automation), 1:20 (Level-3); current multi-drone waivers ~1:4 | **Defensible & well-ordered** — maps onto the automation ladder. Worth documenting the mapping. |
| `deliveries_per_drone_per_day` | 8 / 20 / 30 | Today's real average ≈ 3–8/drone/day; single-package physical ceiling ~40–55/day (1.5 sorties/hr on-pad, 3.5/hr quick-swap). 200+ implies multi-drop, not the same airframe. | pilot=8 = top of *today*; 30 = near the single-package ceiling. Label as near-term; flag that >~50/day needs a multi-drop aircraft. |
| `operator_daily_cost_usd` | 240 ($30/hr × 8h) | Drone-pilot wage: median ~$44.5k–$75k/yr, hourly $25–$75 | Reasonable **base** wage; not fully loaded (no benefits/overhead). |
| `maintenance_daily_cost_usd` | 280 ($35/hr × 8h) | UAV technician ~$24–25/hr → ~$200/day base | **Inverted vs reality** as a pure wage (see audit #2). Defensible only if it bundles parts/tools. |
| `drone_daily_lease_or_depreciation_usd` | 15 | Certified delivery aircraft $50k+; light commercial $10k–50k | **Likely 2–3× low** for a certified BVLOS delivery drone (see audit #3). |
| `charger_daily_cost_usd` | 8 | ~$2.9k/yr amortized pad + energy | Plausible; tiny contributor. Leave. |
| `platform_fixed_cost_usd_day` | 400 / 1,200 / 3,500 | No clean public anchor (depot + software) | Genuinely synthetic. Order-of-magnitude only. Keep, labelled. |
| **Per-delivery overhead (output)** | pilot ≈ $25; scales toward ~$2 | McKinsey: ~$13.50 today; ~$1.50–2 at 1:20 operator scale | **Shape externally corroborated** — strong support for the thesis. |

---

## 1. Staffing ratios — `operator_to_drone_ratio`

This is the strongest number in the model, and it currently reads as
arbitrary. It isn't — it tracks the FAA's automation ladder.

| Regime | Ratio | Model profile at that ratio |
|---|---|---|
| Part 107 today (1 pilot : 1 drone, visual-observer era) | 1:1 | — |
| Current multi-drone BVLOS waivers (e.g. Skydio, public-safety, 2025) | ~1:4 | — |
| **Part 108 NPRM — Level-2 automation** | **>1:5** | `regional_capacity` (0.15 ≈ 1:6.7) |
| **Part 108 NPRM — Level-3 automation** | **>1:20** | (none — `dense_urban` at 1:12.5 sits between L2 and L3) |

- `pilot_capacity` 0.50 = **1:2** — barely past one-pilot-one-drone;
  conservative for an early pilot program. (Arguably could be 1:1 =
  ratio 1.0 to reflect *today's* Part 107 reality; 1:2 assumes a modest
  early waiver.)
- `regional_capacity` 0.15 = **1:6.7** — just past the Part 108
  Level-2 cap. Defensible.
- `dense_urban_capacity` 0.08 = **1:12.5** — between Level-2 and
  Level-3 automation. Defensible as "high-automation dense routing."

**Recommendation:** keep the values, but document this mapping in the
registry comments so the ratio reads as regulation-anchored rather than
guessed. This single addition does the most to give the model
"semblance of reality," because staffing is the binding constraint the
README already calls out (operator wages ≈ 60% of pilot overhead).

`maintenance_staff_per_drone` (0.20 / 0.10 / 0.06) has no clean public
anchor — fleet-maintenance ratios aren't published — but the ordering
(smaller fleets carry proportionally more maintenance overhead) is the
right direction. Leave as synthetic, labelled.

Sources: [FAA Part 108 / BVLOS NPRM (Pilot Institute)](https://pilotinstitute.com/part-108-explained/),
[Skydio multi-drone BVLOS approval](https://www.skydio.com/blog/bvlos-introducing-multi-drone-operations),
[FAA Package Delivery by Drone (Part 135)](https://www.faa.gov/uas/advanced_operations/package_delivery_drone).

## 2. Productivity — `deliveries_per_drone_per_day`

**This model is single-package** (one delivery = one out-and-back
sortie), so productivity is **sortie-bound**, not target-bound. The
often-quoted "200+ / drone / day" figure is *not* a fair ceiling here:
it implies either a **multi-drop payload** (a rack of packages dropped
across one sortie — a different aircraft architecture) or a
per-distribution-center aggregate (e.g. Zipline's ~500/day is *per
center*, not per drone). For a single-package airframe the hard limit
is how many round trips it can physically turn in a day:

| Constraint | Figure |
|---|---|
| Current real-world *average* across operating networks | **3–8 deliveries / drone / day** |
| 30-min on-pad recharge | ≈ 1.5 sorties / hr → **~18–21/day** (12–14 h) |
| 60-second quick-swap battery | ≈ 3.5 sorties / hr → **~42–49/day** (12–14 h) |
| **Realistic single-package ceiling** | **~40–55 / drone / day** |

The model's values (8 / 20 / 30) span *today's reality* up to *near the
single-package physical ceiling*:

- **8** (`pilot_capacity`) = the top of today's real-world average. A
  fair "this is what a real pilot program actually achieves now"
  (on-pad recharge, partial duty cycle).
- **20** (`regional_capacity`) ≈ on-pad recharge (~1.5 sorties/hr) over
  a full ~12-hour operating day.
- **30** (`dense_urban_capacity`) ≈ between on-pad and quick-swap
  turnaround — **near the realistic single-package ceiling (~40–55),
  not far below it.**

**Recommendation:** values are fine; **label them** as near-term scaled
(not present-day) so a reviewer doesn't read 30/day as a measured
figure. Critically, note that **30 is close to the single-package
physical ceiling**, so there is little headroom above it on the same
aircraft. Any future profile above ~40–55/day is no longer "the same
drone flying more" — it implies a **multi-drop aircraft**, which would
also change payload, energy use, and the demand model. The registry
should say this, so nobody adds a `national_capacity = 120` profile
while silently assuming single-drop physics still hold.

Sources: [The $8-per-delivery problem (Low Altitude Economy)](https://lowaltitudeeconomy.aero/evtol-news-and-electric-aircraft-news/cargo-drones/eight-dollar-delivery-problem-ecommerce-drone-last-mile-economics-2030),
[Last-mile drone battery ROI (Herewin)](https://www.herewinpower.com/blog/last-mile-delivery-drone-battery-solutions/),
[Zipline throughput (Contrary Research)](https://research.contrary.com/company/zipline).

## 3. Labour cost — `operator_daily_cost_usd`, `maintenance_daily_cost_usd`

| Role | Public wage data | Implied $/day (8h) |
|---|---|---|
| Drone / UAV pilot | Median ~$44.5k–$75k/yr; hourly $25–$75; realistic Part-107 commercial $57k–$95k | $200–$370 base (median ≈ $240–290) |
| UAV / drone technician | ~$24–25/hr average ($50k–53k/yr) | ~$200 base |

- **Operator $240/day** = $30/hr × 8h. Lands in the low-middle of the
  pilot wage range as a **base** wage. It is *not* fully loaded — real
  employer cost includes benefits, payroll tax, and supervision
  overhead (typically ×1.3–1.4). A fully-loaded operator would be
  ≈ **$310–340/day**. Decide deliberately whether the model is base or
  loaded, and apply the same convention to both roles.
- **Maintenance $280/day** = $35/hr × 8h. The technician wage data says
  ~$25/hr → ~$200/day base. So **as a pure wage, $280 is high and
  out-of-order** (see audit #2 below). The code comment justifies it as
  "slightly higher to reflect parts/tools" — that's a reasonable
  reframing, but then it is a *blended labour+consumables* line, not a
  wage, and should be named/commented that way.

Sources: [Drone Pilot Salary (Salary.com)](https://www.salary.com/research/salary/hiring/drone-pilot-salary),
[Drone Pilot Salary (Indeed)](https://www.indeed.com/career/drone-pilot/salaries),
[UAV Technician Salary (ZipRecruiter)](https://www.ziprecruiter.com/Salaries/Uav-Technician-Salary).

## 4. Capital — `drone_daily_lease_or_depreciation_usd`

| Aircraft class | Unit cost | Straight-line $/day |
|---|---|---|
| Light commercial delivery drone | $10k–50k | 3-yr: $9–46 · 5-yr: $5–27 |
| Certified enterprise / BVLOS delivery aircraft | $50k–400k+ | 3-yr: $46–365 · 5-yr: $27–219 |

**$15/day implies a ~$16k aircraft over 3 years (or ~$27k over 5),
with no financing cost and no battery-replacement reserve.** That's a
*light-commercial* assumption — fine if stated, but low for a certified
BVLOS delivery drone, which is the aircraft class the rest of the model
(Part 108, dense-urban routing) implies.

**Recommendation:** either (a) document $15/day as an explicit
light-commercial assumption, or (b) raise to **$25–45/day** to reflect
a certified delivery aircraft amortized over 3–5 years, plus a battery-
replacement reserve (delivery duty cycles wear packs fast). Note this
is a *flat constant across all three profiles* today — a dense-urban
certified fleet and a pilot program almost certainly fly different
aircraft.

Sources: [Commercial drone cost guide (Robotomated)](https://robotomated.com/learn/cost/drone-cost-guide),
[Best delivery drones 2026 (Jinghong)](https://jinghongdrone.com/best-delivery-drones-for-commercial-use),
[Zipline economics (DroneXL)](https://dronexl.co/2026/01/21/zipline-economics-of-drone-delivery/).

## 5. End-to-end sanity check (the most reassuring result)

McKinsey's last-mile drone cost model is the best external check on the
*output* of our overhead stack:

| McKinsey figure | Our model |
|---|---|
| ~**$13.50** direct operating cost per single-package delivery, *today* | pilot per-delivery overhead ≈ $25 (overhead only; pre-revenue) — same order of magnitude for an early, sub-scale program |
| ~**$1.50–2** per delivery *if one operator manages ~20 drones* | dense-urban / national profiles drive per-delivery overhead toward ~$2 |
| Conclusion: not cost-competitive (vs $9–11 van) until operator-to-drone ratio rises sharply | Exactly the model's thesis: **staffing ratio is the binding lever** |

The model's *shape* — expensive at pilot scale, competitive only when
the operator-to-drone ratio climbs — is the same conclusion McKinsey
reached independently. That's meaningful corroboration that the
overhead structure is wired up correctly, even if individual constants
are synthetic.

Sources: [McKinsey drone-delivery cost model (DroneDJ)](https://dronedj.com/2023/01/12/drone-delivery-cost/),
["Last-mile" drone deliveries may not be cost-competitive — McKinsey (Drone Articles)](https://dronearticles.com/last-mile-drone-package-deliveries-may-not-be-cost-competitive-mckinsey-report-finds/).

---

## Internal-consistency audit

These are the "do the numbers even relate to each other correctly?"
problems — independent of whether any single value is realistic.

1. **Two sources of truth for the same labour constants.**
   `operator_daily_cost_usd = 240` and `maintenance_daily_cost_usd =
   280` are hard-coded in **both** `core/capacity_models.py` (per-profile
   fields) **and** `core/scale_models.py` (`OPERATOR_DAILY_USD` /
   `MAINTENANCE_DAILY_USD` module constants). They happen to match today;
   nothing keeps them in sync. Change one and the two analytical surfaces
   silently disagree. → *Fix: have one registry import the other's
   constants, or move shared labour rates to a single module.*

2. **Wage ordering is inverted vs the labour market.** The model has
   maintenance ($280) **>** operator ($240). Public wage data has the
   pilot ($30–46/hr) **>** the technician (~$25/hr). Either justify
   $280 explicitly as labour **+ parts/tools** (and rename/comment it as
   a blended line), or bring it below the operator rate (~$200/day base).
   As written, a reviewer reading them as two wages sees them backwards.

3. **Capital is likely 2–3× low for the implied aircraft class** (see §4).
   $15/day is a light-commercial drone; the Part 108 / dense-urban framing
   implies a certified aircraft at $25–45/day.

4. **Base-vs-loaded labour convention is unstated.** $240/$280 are bare
   wages with no benefits/overhead multiplier. Whatever convention you
   pick (base or fully-loaded ×1.3–1.4), apply it to *both* roles and
   state it once.

5. **`drone_daily_lease`, `operator_daily`, `maintenance_daily`,
   `charger_daily` are flat across all three capacity profiles.** Only
   the *ratios* and `platform_fixed_cost` vary. That's a defensible
   simplification, but it means a "dense urban" fleet pays the same per
   drone and per operator as a "pilot" fleet — no wage premium for dense
   labour markets, no fleet-discount on aircraft. Worth a one-line
   acknowledgement.

6. **`capacity_models` vs `scale_models` reconciliation debt** (already
   flagged in the code): the per-delivery overhead is computed two
   different ways on two different surfaces. The README's "transition
   state" table documents this; this research doesn't resolve it but
   reinforces that the **labour constants** are the cleanest thing to
   unify first (audit #1).

---

## Suggested next actions (none applied yet)

In priority order, smallest-blast-radius first:

1. **Document the Part 108 ratio mapping** (§1) in the `capacity_models`
   registry comments — pure comment change, highest "realism" payoff.
2. **Unify the duplicated labour constants** (audit #1) — one source of
   truth for `operator_daily` / `maintenance_daily`.
3. **Resolve the wage inversion** (audit #2) — either rename the
   maintenance line as blended labour+parts, or lower it.
4. **Reconsider `drone_daily_lease`** (§4) — document as light-commercial,
   or raise to a certified-aircraft range.
5. **Add near-term-scaled / base-vs-loaded labels** (§2, audit #4) so
   nothing reads as a measured present-day figure.

Each of these is an independent, reviewable change. Per the project's
cleanup convention, they should be applied one at a time with approval,
not as a bulk rewrite.

---

## Sources

- FAA — [Package Delivery by Drone (Part 135)](https://www.faa.gov/uas/advanced_operations/package_delivery_drone)
- Pilot Institute — [Part 108 Explained](https://pilotinstitute.com/part-108-explained/)
- Skydio — [Multi-Drone BVLOS Operations](https://www.skydio.com/blog/bvlos-introducing-multi-drone-operations)
- Low Altitude Economy — [The $8-Per-Delivery Problem](https://lowaltitudeeconomy.aero/evtol-news-and-electric-aircraft-news/cargo-drones/eight-dollar-delivery-problem-ecommerce-drone-last-mile-economics-2030)
- Herewin Power — [Last-Mile Drone Battery ROI](https://www.herewinpower.com/blog/last-mile-delivery-drone-battery-solutions/)
- Contrary Research — [Zipline Business Breakdown](https://research.contrary.com/company/zipline)
- Salary.com — [Drone Pilot Salary](https://www.salary.com/research/salary/hiring/drone-pilot-salary)
- Indeed — [Drone Pilot Salary](https://www.indeed.com/career/drone-pilot/salaries)
- ZipRecruiter — [UAV Technician Salary](https://www.ziprecruiter.com/Salaries/Uav-Technician-Salary)
- Robotomated — [Commercial Drone Cost Guide](https://robotomated.com/learn/cost/drone-cost-guide)
- Jinghong — [Best Delivery Drones for Commercial Use 2026](https://jinghongdrone.com/best-delivery-drones-for-commercial-use)
- DroneXL — [Zipline Economics of Drone Delivery](https://dronexl.co/2026/01/21/zipline-economics-of-drone-delivery/)
- DroneDJ — [McKinsey Drone Delivery Cost Model](https://dronedj.com/2023/01/12/drone-delivery-cost/)
- Drone Articles — [McKinsey: Last-Mile Drone Deliveries May Not Be Cost-Competitive](https://dronearticles.com/last-mile-drone-package-deliveries-may-not-be-cost-competitive-mckinsey-report-finds/)
</content>
</invoke>
