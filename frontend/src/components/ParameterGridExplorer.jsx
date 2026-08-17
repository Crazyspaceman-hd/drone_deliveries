import React, { useState } from 'react';
import { api } from '../api.js';
import { colorForMargin } from './ViabilityGrid.jsx';

/**
 * ParameterGridExplorer — a 2-D viability heatmap.
 *
 * Unlike the main viability grid (capacity_model × delivery_domain),
 * this fixes one base capacity and one domain, then sweeps TWO capacity
 * parameters against each other.  Each cell is a multi-override
 * synthetic capacity (``base@px=vx,py=vy``) colored by its viability
 * margin.  Read-side and ephemeral — recomputed on demand, nothing
 * persisted.
 *
 * This is the "I changed the operator ratio and immediately wanted to
 * also change deliveries-per-drone" view: it shows the *interaction*
 * between two levers, which the 1-D what-if launcher can't.
 */

const CAPACITY_PARAMS = [
  'operator_to_drone_ratio',
  'deliveries_per_drone_per_day',
  'maintenance_staff_per_drone',
  'charger_to_drone_ratio',
  'drone_daily_lease_or_depreciation_usd',
];
const BASES   = ['pilot_capacity', 'regional_capacity', 'dense_urban_capacity'];
const DOMAINS = ['food_delivery', 'medical_delivery', 'retail_package', 'urgent_documents'];

export function ParameterGridExplorer() {
  const [base, setBase]       = useState('pilot_capacity');
  const [domain, setDomain]   = useState('retail_package');
  const [paramX, setParamX]   = useState('operator_to_drone_ratio');
  const [valuesX, setValuesX] = useState('0.6,0.4,0.2');
  const [paramY, setParamY]   = useState('deliveries_per_drone_per_day');
  const [valuesY, setValuesY] = useState('8,16,24,32');
  const [busy, setBusy]       = useState(false);
  const [grid, setGrid]       = useState(null);
  const [error, setError]     = useState(null);

  function parseVals(s) {
    return s.split(',').map((v) => v.trim()).filter(Boolean)
      .map((v) => (isNaN(Number(v)) ? v : Number(v)));
  }

  async function run() {
    setBusy(true); setError(null); setGrid(null);
    try {
      const g = await api.parameterGrid({
        base_capacity: base, domain,
        param_x: paramX, values_x: parseVals(valuesX),
        param_y: paramY, values_y: parseVals(valuesY),
      });
      setGrid(g);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2 className="section-title">Two-parameter explorer</h2>
      <p className="muted section-lead">
        Fix one capacity model and one delivery domain, then sweep two
        capacity parameters against each other. Each cell is a synthetic
        variant with <em>both</em> overrides applied; color is the
        viability margin at the addressable anchor. This shows how two
        levers <em>interact</em> — the diagonal where red turns green is
        the combination that flips viability. Read-only and recomputed on
        demand; nothing is persisted.
      </p>

      <div className="panel">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
          <Picker label="base capacity" value={base} set={setBase} options={BASES} />
          <Picker label="domain" value={domain} set={setDomain} options={DOMAINS} />
          <Picker label="param X (columns)" value={paramX} set={setParamX} options={CAPACITY_PARAMS} />
          <TextField label="values X" value={valuesX} set={setValuesX} />
          <Picker label="param Y (rows)" value={paramY} set={setParamY} options={CAPACITY_PARAMS} />
          <TextField label="values Y" value={valuesY} set={setValuesY} />
          <button onClick={run} disabled={busy}
                  style={{ padding: '6px 16px', cursor: busy ? 'wait' : 'pointer' }}>
            {busy ? 'Computing…' : 'Compute grid'}
          </button>
        </div>
        {error && <p className="error" style={{ marginTop: 10 }}>{error}</p>}
      </div>

      {grid && <Heatmap grid={grid} />}
    </section>
  );
}

function Picker({ label, value, set, options }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', fontSize: 12 }}>
      <span className="muted">{label}</span>
      <select value={value} onChange={(e) => set(e.target.value)}>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

function TextField({ label, value, set }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', fontSize: 12 }}>
      <span className="muted">{label}</span>
      <input className="mono" value={value} onChange={(e) => set(e.target.value)}
             style={{ width: 120 }} />
    </label>
  );
}

function Heatmap({ grid }) {
  const maxAbs = grid.margin_max_abs || 0;
  const byCell = {};
  for (const c of grid.cells) byCell[`${c.x}|${c.y}`] = c;

  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        {grid.base_capacity} × {grid.domain} — columns vary{' '}
        <span className="mono">{grid.param_x}</span>, rows vary{' '}
        <span className="mono">{grid.param_y}</span>.
      </p>
      <div className="panel matrix-wrap">
        <table className="matrix-table">
          <thead>
            <tr>
              <th><span className="mono">{grid.param_y}</span> ↓ / <span className="mono">{grid.param_x}</span> →</th>
              {grid.values_x.map((vx) => <th key={vx} className="mono">{vx}</th>)}
            </tr>
          </thead>
          <tbody>
            {grid.values_y.map((vy) => (
              <tr key={vy}>
                <th className="mono row-head">{vy}</th>
                {grid.values_x.map((vx) => {
                  const c = byCell[`${vx}|${vy}`];
                  const m = c ? c.viability_margin : null;
                  const color = (m === null || m === undefined)
                    ? '#eeeeee' : colorForMargin(m, maxAbs);
                  return (
                    <td key={vx} className="mono"
                        title={c ? `${c.synthetic_name}\nmargin ${m === null ? 'n/a' : '$' + m.toFixed(2) + '/del.'}\nbreakeven ${c.breakeven_deliveries_per_day ?? 'never'}` : ''}
                        style={{ backgroundColor: color, textAlign: 'center' }}>
                      {m === null || m === undefined ? '—'
                        : `${m >= 0 ? '+' : ''}$${m.toFixed(2)}`}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
