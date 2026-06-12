import React, { useState } from 'react';
import { api, chartUrl } from '../api.js';
import { useApi } from './useApi.js';

const CAPACITY_MODELS = ['pilot_capacity', 'regional_capacity', 'dense_urban_capacity'];

/**
 * Service-mix analysis (Phase 33).  Weighted multi-domain portfolios as
 * an analytical overlay on top of the existing pure-domain economics.
 * Split-volume: each component is served at total × weight.
 */
export function ServiceMixAnalysis() {
  const [cap, setCap] = useState('pilot_capacity');
  const { data, error, loading } = useApi(() => api.serviceMixes(cap), [cap]);

  return (
    <section>
      <h2 className="section-title">Service-mix analysis</h2>
      <p className="muted section-lead">
        Pure delivery domains still exist above. A <strong>service mix</strong> is
        a named <em>weighted portfolio</em> of those domains — one operator
        serving blended demand. These are analytical overlays, not new
        simulated event streams. Split-volume model: a mix at total V
        serves each component at <span className="mono">V × weight</span>,
        keeping it within that domain's addressable demand; capacity
        overhead is shared across the whole mix.
      </p>

      <div className="panel">
        <div className="scenario-tabs" style={{ marginBottom: 12 }}>
          <span className="muted" style={{ marginRight: 8 }}>capacity model:</span>
          {CAPACITY_MODELS.map((name) => (
            <button key={name}
              className={`scenario-tab${name === cap ? ' active' : ''}`}
              onClick={() => setCap(name)}>{name}</button>
          ))}
        </div>

        {loading && <p className="muted">Computing service mixes…</p>}
        {error   && <p className="error">{error}</p>}

        {data && (data.rows?.length ? (
          <>
            <MixTable data={data} />
            {data.service_mixes && <MixLegend mixes={data.service_mixes} />}
          </>
        ) : (
          <div className="empty-state">
            No economics snapshots for the mix component domains. Run:
            <pre className="mono">{`python run_transforms.py --all-runs
python run_transforms.py --all-runs --all-delivery-domains`}</pre>
          </div>
        ))}
      </div>

      <div className="chart-grid">
        <figure>
          <img src={chartUrl('service_mix_profit_by_volume.png')}
               alt="Service-mix effective profit by volume"
               onError={(e) => { e.currentTarget.style.display = 'none'; }} />
          <figcaption>
            <div className="mono">service_mix_profit_by_volume.png</div>
            <div className="muted">
              One line per mix at the default capacity. Dashed where a
              component exceeds its addressable demand. (PNG renders at
              the default capacity; the table above is live per capacity.)
            </div>
          </figcaption>
        </figure>
      </div>
    </section>
  );
}

function MixTable({ data }) {
  // Pick a representative mid-volume row per mix for the compact table.
  const byMix = {};
  for (const r of data.rows) {
    (byMix[r.service_mix_name] = byMix[r.service_mix_name] || []).push(r);
  }
  const rows = Object.entries(byMix).map(([name, rs]) => {
    const sorted = [...rs].sort((a, b) => a.deliveries_per_day - b.deliveries_per_day);
    return sorted[Math.floor(sorted.length / 2)];  // mid volume
  }).sort((a, b) => b.avg_effective_profit - a.avg_effective_profit);

  return (
    <table>
      <thead>
        <tr>
          <th>service mix</th>
          <th>deliveries/day</th>
          <th>capacity</th>
          <th>avg effective profit</th>
          <th>break-even rate</th>
          <th>best component</th>
          <th>worst component</th>
          <th>components</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.service_mix_name}>
            <td className="mono">{r.service_mix_name}</td>
            <td className="mono">{r.deliveries_per_day.toLocaleString()}</td>
            <td className="mono">{r.capacity_model}</td>
            <td className={`mono ${r.avg_effective_profit >= 0 ? 'numpos' : 'numneg'}`}>
              ${r.avg_effective_profit.toFixed(2)}
            </td>
            <td className="mono">{(r.break_even_rate * 100).toFixed(0)}%</td>
            <td className="mono">{r.best_component_domain}</td>
            <td className="mono">{r.worst_component_domain}</td>
            <td className="mono" style={{ fontSize: 11 }}>
              {r.components.map((c) =>
                `${(c.mix_weight * 100).toFixed(0)}% ${c.component_domain}`).join(' · ')}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MixLegend({ mixes }) {
  return (
    <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
      {mixes.map((m) => (
        <span key={m.name} style={{ display: 'block' }}>
          <span className="mono">{m.name}</span> — {m.description}
        </span>
      ))}
    </p>
  );
}
