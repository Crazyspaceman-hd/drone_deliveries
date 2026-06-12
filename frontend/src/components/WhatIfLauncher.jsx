import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api.js';

/**
 * WhatIfLauncher — a small controlled-experiment launcher.
 *
 * The reviewer picks a dimension, a base profile, a parameter, and a
 * comma-separated list of values, then hits "Run what-if".  Behind the
 * scenes this POSTs to /experiments/what-if, which reuses the same
 * experiment runner as named experiments.  Capacity sweeps are
 * read-side (no new snapshots); domain sweeps write economics
 * snapshots.  Either way the synthetic variants then appear in the
 * viability grid alongside the registered profiles.
 *
 * Allowed parameters per dimension are a curated subset of the most
 * portfolio-relevant fields — not every dataclass field, to keep the
 * UI honest about what's worth sweeping.
 */

const PARAMS_BY_DIMENSION = {
  capacity_model: {
    bases: ['pilot_capacity', 'regional_capacity', 'dense_urban_capacity'],
    params: [
      'operator_to_drone_ratio',
      'deliveries_per_drone_per_day',
      'maintenance_staff_per_drone',
      'charger_to_drone_ratio',
      'drone_daily_lease_or_depreciation_usd',
    ],
    exampleValues: '0.60,0.45,0.30,0.20',
  },
  delivery_domain: {
    bases: ['food_delivery', 'medical_delivery', 'retail_package', 'urgent_documents'],
    params: [
      'saturation_volume_per_day',
      'volume_efficiency_gain_rate',
      'volume_value_decay_rate',
    ],
    exampleValues: '1500,2500,4000,5500',
  },
};

export function WhatIfLauncher() {
  const [dimension, setDimension] = useState('capacity_model');
  const [base, setBase]           = useState('pilot_capacity');
  const [parameter, setParameter] = useState('operator_to_drone_ratio');
  const [values, setValues]       = useState('0.60,0.45,0.30,0.20');
  const [busy, setBusy]           = useState(false);
  const [result, setResult]       = useState(null);
  const [error, setError]         = useState(null);

  const cfg = PARAMS_BY_DIMENSION[dimension];

  function onDimensionChange(d) {
    setDimension(d);
    const next = PARAMS_BY_DIMENSION[d];
    setBase(next.bases[0]);
    setParameter(next.params[0]);
    setValues(next.exampleValues);
    setResult(null);
    setError(null);
  }

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const parsed = values.split(',').map((v) => v.trim()).filter(Boolean)
        .map((v) => (isNaN(Number(v)) ? v : Number(v)));
      const body = { dimension, base, parameter, values: parsed };
      const r = await api.whatIf(body);
      setResult(r);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2 className="section-title">What-if launcher</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        What-if experiments create synthetic profile variants using the
        same pipeline as named experiments. They do not mutate the base
        profiles. Results are recorded as experiment outputs and appear
        in the <Link to="/domain-scale">viability grid</Link> alongside
        registered profiles.
      </p>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
        <label style={{ display: 'flex', flexDirection: 'column', fontSize: 12 }}>
          <span className="muted">dimension</span>
          <select value={dimension} onChange={(e) => onDimensionChange(e.target.value)}>
            <option value="capacity_model">capacity_model</option>
            <option value="delivery_domain">delivery_domain</option>
          </select>
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', fontSize: 12 }}>
          <span className="muted">base</span>
          <select value={base} onChange={(e) => setBase(e.target.value)}>
            {cfg.bases.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', fontSize: 12 }}>
          <span className="muted">parameter</span>
          <select value={parameter} onChange={(e) => setParameter(e.target.value)}>
            {cfg.params.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', fontSize: 12, flex: 1, minWidth: 160 }}>
          <span className="muted">values (comma-separated)</span>
          <input value={values} onChange={(e) => setValues(e.target.value)}
                 className="mono" />
        </label>

        <button onClick={run} disabled={busy}
                style={{ padding: '6px 16px', cursor: busy ? 'wait' : 'pointer' }}>
          {busy ? 'Running…' : 'Run what-if'}
        </button>
      </div>

      {error && <p className="error" style={{ marginTop: 10 }}>{error}</p>}

      {result && (
        <div className="panel" style={{ marginTop: 12, background: '#eef7ee' }}>
          <strong>Created experiment {result.experiment_name}</strong>
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            {result.dimension === 'capacity_model'
              ? 'Read-side capacity variants — no new snapshots written; '
              : 'Domain variants written to economics snapshots; '}
            now visible in the viability grid.
          </div>
          <table className="kv" style={{ marginTop: 8 }}>
            <tbody>
              <tr><td className="muted">synthetic names</td>
                  <td className="mono">
                    {result.synthetic_names.map((n) => <div key={n}>{n}</div>)}
                  </td></tr>
              <tr><td className="muted">experiment_run_id</td>
                  <td className="mono">{result.experiment_run_id}</td></tr>
            </tbody>
          </table>
          <p style={{ marginTop: 8 }}>
            <Link to="/domain-scale">View in the viability grid →</Link>
          </p>
        </div>
      )}
    </section>
  );
}
