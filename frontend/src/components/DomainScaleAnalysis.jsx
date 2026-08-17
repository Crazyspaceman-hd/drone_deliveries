import React, { useState } from 'react';
import { api, chartUrl } from '../api.js';
import { useApi } from './useApi.js';
import { ViabilityGrid } from './ViabilityGrid.jsx';
import { ServiceMixAnalysis } from './ServiceMixAnalysis.jsx';

/**
 * The key business-facing analytical surface: how do delivery domains and
 * scale models change outcomes?  Read-only window into the snapshot tables.
 */
export function DomainScaleAnalysis() {
  const domainCall = useApi(api.deliveryDomains);
  const scaleCall  = useApi(api.scaleModels);
  const matrixCall = useApi(api.domainScaleMatrix);

  return (
    <div>
      <p className="muted section-lead">
        The same operational event stream is reinterpreted under four
        delivery-domain assumptions and four fleet-scale assumptions.
        Only the demand-side and overhead numbers move — physics
        (distance, energy, telemetry) stays fixed.
      </p>

      <DomainProfiles    call={domainCall} />
      <ScaleProfiles     call={scaleCall} />
      <Matrix            call={matrixCall} />
      <VolumeSensitivity />
      <ServiceMixAnalysis />
      <ChartPair />
    </div>
  );
}

function DomainProfiles({ call }) {
  if (call.loading) return <section className="panel muted">Loading delivery domains…</section>;
  if (call.error)   return <section className="panel error">{call.error}</section>;
  const profiles = call.data?.profiles || [];
  const snaps    = call.data?.latest_snapshots || [];
  return (
    <section>
      <h2 className="section-title">Delivery-domain profiles</h2>
      {!profiles.length ? (
        <div className="empty-state">
          No delivery-domain profiles registered.
        </div>
      ) : (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>domain</th>
                <th>fee multiplier</th>
                <th>avg order value</th>
                <th>premium share</th>
                <th>payload kg</th>
              </tr>
            </thead>
            <tbody>
              {profiles.map((p) => (
                <tr key={p.name}>
                  <td className="mono">{p.name}</td>
                  <td className="mono">{p.delivery_fee_multiplier?.toFixed?.(2) ?? p.delivery_fee_multiplier}</td>
                  <td className="mono">${p.average_order_value_usd?.toFixed?.(2) ?? p.average_order_value_usd}</td>
                  <td className="mono">{(p.premium_share * 100)?.toFixed?.(0) ?? p.premium_share}%</td>
                  <td className="mono">{p.payload_kg_mean?.toFixed?.(2) ?? p.payload_kg_mean}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="section-subtitle">Latest snapshots by (scenario, domain)</h3>
      {!snaps.length ? (
        <div className="empty-state">
          No snapshots yet.  Run:
          <pre className="mono">python run_transforms.py --all-runs --all-delivery-domains</pre>
        </div>
      ) : (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>scenario</th>
                <th>domain</th>
                <th>avg revenue</th>
                <th>avg op cost</th>
                <th>avg profit / trip</th>
                <th>snapshots</th>
              </tr>
            </thead>
            <tbody>
              {snaps.map((s) => (
                <tr key={`${s.scenario_name}|${s.domain_name}`}>
                  <td className="mono">{s.scenario_name}</td>
                  <td className="mono">{s.domain_name}</td>
                  <td className="mono">${s.avg_revenue_per_trip?.toFixed(2)}</td>
                  <td className="mono">${s.avg_operational_cost_per_trip?.toFixed(2)}</td>
                  <td className={`mono ${s.avg_profit_per_trip >= 0 ? 'numpos' : 'numneg'}`}>
                    ${s.avg_profit_per_trip?.toFixed(2)}
                  </td>
                  <td className="mono">{s.snapshot_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ScaleProfiles({ call }) {
  if (call.loading) return <section className="panel muted">Loading scale models…</section>;
  if (call.error)   return <section className="panel error">{call.error}</section>;
  const profiles = call.data?.profiles || [];
  const snaps    = call.data?.latest_snapshots || [];
  return (
    <section>
      <h2 className="section-title">Scale-model profiles</h2>
      {!profiles.length ? (
        <div className="empty-state">No scale-model profiles registered.</div>
      ) : (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>scale model</th>
                <th>fleet size</th>
                <th>annual trips</th>
                <th>fixed overhead</th>
                <th>per-trip overhead</th>
              </tr>
            </thead>
            <tbody>
              {profiles.map((p) => (
                <tr key={p.name}>
                  <td className="mono">{p.name}</td>
                  <td className="mono">{p.fleet_size}</td>
                  <td className="mono">{p.annual_trip_capacity?.toLocaleString?.() ?? p.annual_trip_capacity}</td>
                  <td className="mono">${p.fixed_annual_overhead_usd?.toLocaleString?.() ?? p.fixed_annual_overhead_usd}</td>
                  <td className="mono">${p.amortized_overhead_per_trip?.toFixed?.(2) ?? p.amortized_overhead_per_trip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="section-subtitle">Latest snapshots by (scenario, scale)</h3>
      {!snaps.length ? (
        <div className="empty-state">
          No snapshots yet.  Run:
          <pre className="mono">python run_transforms.py --all-runs --all-scale-models</pre>
        </div>
      ) : (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>scenario</th>
                <th>scale model</th>
                <th>op cost</th>
                <th>amortized overhead</th>
                <th>effective profit</th>
                <th>break-even trips</th>
              </tr>
            </thead>
            <tbody>
              {snaps.map((s) => (
                <tr key={`${s.scenario_name}|${s.scale_model_name}`}>
                  <td className="mono">{s.scenario_name}</td>
                  <td className="mono">{s.scale_model_name}</td>
                  <td className="mono">${s.avg_operational_cost?.toFixed(2)}</td>
                  <td className="mono">${s.avg_amortized_overhead?.toFixed(2)}</td>
                  <td className={`mono ${s.avg_effective_profit >= 0 ? 'numpos' : 'numneg'}`}>
                    ${s.avg_effective_profit?.toFixed(2)}
                  </td>
                  <td className="mono">{s.trips_break_even} / {s.snapshot_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Matrix({ call }) {
  const [scenario, setScenario] = useState(null);
  if (call.loading) return <section className="panel muted">Loading domain × scale matrix…</section>;
  if (call.error)   return <section className="panel error">{call.error}</section>;
  const cells   = call.data?.cells || [];
  const best    = call.data?.best_cell;
  const worst   = call.data?.worst_cell;
  const domains = call.data?.domains || [];
  const scales  = call.data?.scale_models || [];

  if (!cells.length) {
    return (
      <section>
        <h2 className="section-title">Domain × Scale matrix</h2>
        <div className="empty-state">
          No (scenario, domain, scale) snapshot triples found.  To populate:
          <pre className="mono">{`python run_transforms.py --all-runs --all-delivery-domains
python run_transforms.py --all-runs --all-scale-models`}</pre>
        </div>
      </section>
    );
  }

  const scenarios = [...new Set(cells.map((c) => c.scenario_name))].sort();
  const activeScenario = scenario || scenarios[0];
  const cellsForScenario = cells.filter((c) => c.scenario_name === activeScenario);
  const byPair = {};
  for (const c of cellsForScenario) {
    byPair[`${c.domain_name}|${c.scale_model_name}`] = c;
  }
  const fmt = (n) => (n == null ? '—' : `$${n.toFixed(2)}`);

  return (
    <section>
      <h2 className="section-title">Domain × Scale matrix</h2>
      <p className="muted">
        Each cell is the average effective profit per trip for one
        (scenario, domain, scale) triple — best-case minus amortized
        overhead.  Pick a scenario:
      </p>
      <div className="scenario-tabs">
        {scenarios.map((s) => (
          <button
            key={s}
            className={`scenario-tab${s === activeScenario ? ' active' : ''}`}
            onClick={() => setScenario(s)}
          >
            {s}
          </button>
        ))}
      </div>
      <div className="panel matrix-wrap">
        <table className="matrix-table">
          <thead>
            <tr>
              <th>domain ↓ / scale →</th>
              {scales.map((sm) => <th key={sm} className="mono">{sm}</th>)}
            </tr>
          </thead>
          <tbody>
            {domains.map((d) => (
              <tr key={d}>
                <th className="mono row-head">{d}</th>
                {scales.map((sm) => {
                  const c = byPair[`${d}|${sm}`];
                  if (!c) return <td key={sm} className="muted">—</td>;
                  const cls = `mono ${c.avg_effective_profit >= 0 ? 'numpos' : 'numneg'}`
                    + (best && c === byPair[`${best.domain_name}|${best.scale_model_name}`]
                       && best.scenario_name === activeScenario ? ' best' : '')
                    + (worst && c === byPair[`${worst.domain_name}|${worst.scale_model_name}`]
                       && worst.scenario_name === activeScenario ? ' worst' : '');
                  return (
                    <td key={sm} className={cls} title={`break-even ${(c.break_even_rate*100).toFixed(0)}% of ${c.trip_count} trips`}>
                      {fmt(c.avg_effective_profit)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {best && (
        <p className="muted">
          Globally best: <span className="mono">{best.scenario_name}</span> /
          {' '}<span className="mono">{best.domain_name}</span> /
          {' '}<span className="mono">{best.scale_model_name}</span> at $
          {best.avg_effective_profit.toFixed(2)} / trip.
        </p>
      )}
    </section>
  );
}

const CAPACITY_MODEL_NAMES = [
  'pilot_capacity', 'regional_capacity', 'dense_urban_capacity',
];


function VolumeSensitivity() {
  const [capacityModel, setCapacityModel] = useState('pilot_capacity');
  const { data, error, loading } = useApi(
    () => api.volumeSensitivity(capacityModel), [capacityModel]
  );

  return (
    <section>
      <h2 className="section-title">Volume sensitivity (capacity-coupled)</h2>
      <p className="muted section-lead">
        Sweeps <span className="mono">deliveries_per_day</span> and derives
        required fleet capacity (drones, operators, chargers, maintenance)
        from the chosen capacity model.  Daily overhead is the sum of
        per-resource daily costs at the derived capacity, not a flat
        number divided by volume.  Read-only — does not write to any
        snapshot table.
      </p>

      <div className="panel" style={{ background: '#fdfaf2', borderColor: '#e8d8a8' }}>
        <strong>Transition state.</strong>{' '}
        This section uses the Phase 28 capacity-coupled overhead model
        plus Phase 29 synthetic domain volume response.  The (domain ×
        scale) matrix above and the Main Finding page's "best combination"
        card still use the original Phase 23 fixed-overhead formula with
        no response layer.  Numbers between the two views may disagree;
        a future phase will reconcile.
      </div>

      <ViabilityGrid />

      <div className="panel muted">
        <strong>Domain volume response is synthetic.</strong>{' '}
        It models how a domain's average per-delivery <em>value</em> and
        <em>operating efficiency</em> may shift as volume grows
        (premium dilution, routing density, shared maintenance).
        Two bounded terms — <span className="mono">efficiency_credit</span>{' '}
        and <span className="mono">value_decay</span> — both saturate at
        each domain's registered{' '}
        <span className="mono">saturation_volume_per_day</span>, which is
        also treated as that domain's <em>addressable-demand ceiling</em>:
        cells past it are dimmed in the table below and rendered as
        dashed line in the chart pair to signal extrapolation. This is a
        transparent comparative assumption layer, not measured demand
        elasticity.
      </div>

      <div className="panel">
        <div className="scenario-tabs" style={{ marginBottom: 12 }}>
          <span className="muted" style={{ marginRight: 8 }}>capacity model:</span>
          {CAPACITY_MODEL_NAMES.map((name) => (
            <button
              key={name}
              className={`scenario-tab${name === capacityModel ? ' active' : ''}`}
              onClick={() => setCapacityModel(name)}
            >
              {name}
            </button>
          ))}
        </div>

        {loading && <p className="muted">Computing sweep…</p>}
        {error   && <p className="error">{error}</p>}

        {data && (
          <>
            <CapacityAssumptions data={data} />

            {data.rows?.length === 0 ? (
              <div className="empty-state">
                No economics snapshots to sweep over.  Run:
                <pre className="mono">{`python run_transforms.py --all-runs
python run_transforms.py --all-runs --all-delivery-domains`}</pre>
              </div>
            ) : (
              <VolumeSensitivityTable rows={data.rows} />
            )}
          </>
        )}
      </div>

      <div className="chart-grid">
        <figure>
          <img
            src={chartUrl('viability_by_capacity_and_domain.png')}
            alt="Viability by capacity model and delivery domain"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
          <figcaption>
            <div className="mono">viability_by_capacity_and_domain.png</div>
            <div className="muted">
              Phase 29 rev — the answer card.  Same 3×4 grid as the
              <em> Viability summary</em> table above, rendered for
              embedding in reports / README.
            </div>
          </figcaption>
        </figure>
        <figure>
          <img
            src={chartUrl('capacity_coupled_profit_by_volume.png')}
            alt="Capacity-coupled effective profit by delivery volume (small multiples)"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
          <figcaption>
            <div className="mono">capacity_coupled_profit_by_volume.png</div>
            <div className="muted">
              Phase 29 rev — small multiples.  One panel per capacity
              model (pilot → regional → dense_urban), four domain curves
              per panel, shared y-axis.  Solid = within addressable
              demand; dashed = formula extrapolation past the ceiling.
            </div>
          </figcaption>
        </figure>
        <figure>
          <img
            src={chartUrl('required_drones_by_delivery_volume.png')}
            alt="Required drones by delivery volume"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
          <figcaption>
            <div className="mono">required_drones_by_delivery_volume.png</div>
            <div className="muted">
              The lever that drives the new overhead.  Domain-independent
              by construction.
            </div>
          </figcaption>
        </figure>
        <figure>
          <img
            src={chartUrl('domain_response_components_by_volume.png')}
            alt="Domain volume-response decomposition"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
          <figcaption>
            <div className="mono">domain_response_components_by_volume.png</div>
            <div className="muted">
              Phase 29 — decomposition.  Small multiples, one panel per
              delivery domain, showing the efficiency credit (cost-side
              gain), value decay (revenue-side loss), and their net.
              Both terms are bounded; reading this alongside the
              composite chart explains <em>what</em> is moving each
              domain's curve.
            </div>
          </figcaption>
        </figure>
        <figure>
          <img
            src={chartUrl('effective_profit_by_delivery_volume.png')}
            alt="[Phase 27 legacy] Effective profit by delivery volume"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
          <figcaption>
            <div className="mono">effective_profit_by_delivery_volume.png</div>
            <div className="muted">
              <strong>Phase 27 legacy view.</strong>  Smooth 1/x curve
              from the fixed-overhead formula.  Kept as the visible
              "before" so the correction is reviewable side-by-side.
            </div>
          </figcaption>
        </figure>
        <figure>
          <img
            src={chartUrl('amortized_overhead_by_delivery_volume.png')}
            alt="[Phase 27 legacy] Amortized overhead by delivery volume"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
          <figcaption>
            <div className="mono">amortized_overhead_by_delivery_volume.png</div>
            <div className="muted">
              <strong>Phase 27 legacy view.</strong>  Pure 1/x decay of
              daily overhead — exactly what Phase 28 corrects.
            </div>
          </figcaption>
        </figure>
      </div>
    </section>
  );
}

function CapacityAssumptions({ data }) {
  const a = data.capacity_assumptions || {};
  return (
    <p className="muted">
      <strong>{data.capacity_model}</strong>:{' '}
      <span className="mono">{a.deliveries_per_drone_per_day?.toFixed?.(0)}</span>{' '}
      deliveries/drone/day,{' '}
      <span className="mono">{a.operator_to_drone_ratio}</span> operator-to-drone,{' '}
      <span className="mono">{a.charger_to_drone_ratio}</span> charger-to-drone.
      Drone lease ${a.drone_daily_lease_or_depreciation_usd}/day; operator ${a.operator_daily_cost_usd}/day;
      maintenance ${a.maintenance_daily_cost_usd}/day; platform ${a.platform_fixed_cost_usd_day}/day.
      Sweep: {data.sweep_points?.[0]}…{data.sweep_points?.[data.sweep_points.length - 1]} deliveries/day
      ({data.sweep_points?.length} points).
    </p>
  );
}

function VolumeSensitivityTable({ rows }) {
  // Two stacked tables:
  //   1. capacity-by-sweep-point — required drones / overhead per delivery
  //      (domain-independent; one row of capacity per sweep point).
  //   2. effective profit pivot — domain × sweep point.
  const byPoint = {};
  const byDomain = {};
  for (const r of rows) {
    byPoint[r.deliveries_per_day] = r;  // overhead/drones identical across domains
    (byDomain[r.delivery_domain] = byDomain[r.delivery_domain] || {})[r.deliveries_per_day] = r;
  }
  const sortedPoints  = Object.keys(byPoint).map(Number).sort((a, b) => a - b);
  const sortedDomains = Object.keys(byDomain).sort();

  return (
    <>
      <h3 className="section-subtitle">Required capacity per sweep point</h3>
      <div className="matrix-wrap">
        <table className="matrix-table">
          <thead>
            <tr>
              <th>deliveries/day →</th>
              {sortedPoints.map((d) => <th key={d} className="mono">{d.toLocaleString()}</th>)}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th className="row-head">required drones</th>
              {sortedPoints.map((d) => (
                <td key={d} className="mono">{byPoint[d].required_drones}</td>
              ))}
            </tr>
            <tr>
              <th className="row-head">required operators</th>
              {sortedPoints.map((d) => (
                <td key={d} className="mono">{byPoint[d].required_operators}</td>
              ))}
            </tr>
            <tr>
              <th className="row-head">required chargers</th>
              {sortedPoints.map((d) => (
                <td key={d} className="mono">{byPoint[d].required_chargers}</td>
              ))}
            </tr>
            <tr>
              <th className="row-head">daily overhead</th>
              {sortedPoints.map((d) => (
                <td key={d} className="mono">${byPoint[d].daily_capacity_overhead.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
              ))}
            </tr>
            <tr>
              <th className="row-head">overhead / delivery</th>
              {sortedPoints.map((d) => (
                <td key={d} className="mono">${byPoint[d].capacity_overhead_per_delivery.toFixed(2)}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      <h3 className="section-subtitle">Avg effective profit per trip (domain × volume)</h3>
      <div className="matrix-wrap">
        <table className="matrix-table">
          <thead>
            <tr>
              <th>deliveries/day →<br/>domain ↓</th>
              {sortedPoints.map((d) => <th key={d} className="mono">{d.toLocaleString()}</th>)}
            </tr>
          </thead>
          <tbody>
            {sortedDomains.map((dom) => (
              <tr key={dom}>
                <th className="mono row-head">{dom}</th>
                {sortedPoints.map((d) => {
                  const r = byDomain[dom][d];
                  if (!r) return <td key={d} className="muted">—</td>;
                  const p = r.avg_effective_profit;
                  const beyond = r.within_addressable_demand === false;
                  const tipLead = beyond
                    ? '⚠ beyond this domain’s addressable demand — extrapolation only · '
                    : '';
                  return (
                    <td
                      key={d}
                      className={`mono ${p >= 0 ? 'numpos' : 'numneg'}`}
                      style={beyond
                        ? { opacity: 0.45, fontStyle: 'italic' }
                        : undefined}
                      title={
                        tipLead +
                        `source profit $${r.avg_source_profit.toFixed(2)}  •  ` +
                        `overhead/delivery $${r.capacity_overhead_per_delivery.toFixed(2)}  •  ` +
                        `efficiency credit +$${r.domain_efficiency_credit.toFixed(2)}  •  ` +
                        `value decay −$${r.domain_value_decay.toFixed(2)}  •  ` +
                        `net response $${r.net_domain_response.toFixed(2)}  •  ` +
                        `break-even ${(r.break_even_rate * 100).toFixed(0)}% of ${r.trip_count} trips`
                      }
                    >
                      {`$${p.toFixed(2)}`}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function ChartPair() {
  // These chart names are produced by core/visualizations.py when domain
  // and scale snapshots exist.  Use <img> directly; the route returns 404
  // and we fall back to an empty-state caption.
  const charts = [
    {
      name: 'revenue_by_delivery_domain.png',
      caption: 'Revenue by delivery domain (latest snapshots)',
    },
    {
      name: 'cost_per_delivery_by_scale.png',
      caption: 'Cost per delivery by scale model',
    },
  ];
  return (
    <section>
      <h2 className="section-title">Supporting charts</h2>
      <div className="chart-grid">
        {charts.map((c) => (
          <figure key={c.name}>
            <img
              src={chartUrl(c.name)}
              alt={c.caption}
              onError={(e) => {
                e.currentTarget.style.display = 'none';
                e.currentTarget.parentNode.classList.add('chart-missing');
              }}
            />
            <figcaption>{c.caption}</figcaption>
          </figure>
        ))}
      </div>
      <p className="muted">
        Missing a chart?  Run{' '}
        <span className="mono">python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts</span>.
      </p>
    </section>
  );
}
