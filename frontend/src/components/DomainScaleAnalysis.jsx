import React, { useState } from 'react';
import { api, chartUrl } from '../api.js';
import { useApi } from './useApi.js';

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

      <DomainProfiles call={domainCall} />
      <ScaleProfiles  call={scaleCall} />
      <Matrix         call={matrixCall} />
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
        (scenario, domain, scale) triple — best-case minus amortised
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
