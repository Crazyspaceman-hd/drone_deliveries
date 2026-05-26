import React, { useEffect, useState } from 'react';
import { api, chartUrl } from '../api.js';

function numFmt(n) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function diffClass(n) {
  if (n === null || n === undefined) return '';
  return n >= 0 ? 'numpos' : 'numneg';
}

export function DeliveryImpactView() {
  const [truckCost, setTruckCost] = useState(12);
  const [data,    setData]    = useState(null);
  const [error,   setError]   = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.displacement(truckCost)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e.message || String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [truckCost]);

  if (loading) return <div className="panel muted">Computing displacement…</div>;
  if (error)   return <div className="panel error">{error}</div>;
  if (!data)   return <div className="panel muted">No data.</div>;

  const totals      = data.totals      || {};
  const byScenario  = data.by_scenario || [];

  return (
    <>
      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>
          Synthetic delivery displacement
        </h2>
        <p className="muted" style={{ margin: '0 0 12px' }}>
          One drone delivery is assumed to displace one truck delivery. Truck
          cost per delivery is a placeholder you can edit below.
        </p>
        <label className="mono" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          truck_cost_per_delivery:
          <input
            type="number"
            value={truckCost}
            min={0}
            step={0.5}
            onChange={(e) => setTruckCost(Number(e.target.value) || 0)}
            style={{ width: 80, padding: '2px 6px' }}
          />
          <span className="muted">(synthetic units)</span>
        </label>
      </div>

      <div className="panel">
        <div className="metric-grid">
          <div className="metric">
            <div className="label">Completed drone deliveries</div>
            <div className="value">{numFmt(totals.completed_drone_deliveries)}</div>
          </div>
          <div className="metric">
            <div className="label">Estimated truck cost displaced</div>
            <div className="value">{numFmt(totals.estimated_truck_delivery_cost)}</div>
          </div>
          <div className="metric">
            <div className="label">Drone operational cost</div>
            <div className="value">{numFmt(totals.estimated_drone_operational_cost)}</div>
          </div>
          <div className="metric">
            <div className="label">Cost difference (truck − drone)</div>
            <div className={`value ${diffClass(totals.estimated_cost_difference)}`}>
              {numFmt(totals.estimated_cost_difference)}
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>By scenario</h2>
        <table>
          <thead>
            <tr>
              <th>scenario</th>
              <th>deliveries</th>
              <th>truck cost</th>
              <th>drone op cost</th>
              <th>cost difference</th>
            </tr>
          </thead>
          <tbody>
            {byScenario.map((r) => (
              <tr key={r.scenario_name}>
                <td>{r.scenario_name}</td>
                <td className="mono">{numFmt(r.completed_drone_deliveries)}</td>
                <td className="mono">{numFmt(r.estimated_truck_delivery_cost)}</td>
                <td className="mono">{numFmt(r.estimated_drone_operational_cost)}</td>
                <td className={`mono ${diffClass(r.estimated_cost_difference)}`}>
                  {numFmt(r.estimated_cost_difference)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Chart</h2>
        <p className="muted" style={{ margin: '0 0 8px' }}>
          Rendered server-side from the current SQLite snapshot. Re-run
          {' '}<span className="mono">python run_visualizations.py</span> after a
          new simulation.
        </p>
        <img
          src={chartUrl('delivery_displacement_savings.png')}
          alt="Delivery displacement savings chart"
          style={{ maxWidth: '100%', border: '1px solid var(--border)' }}
        />
      </div>
    </>
  );
}
