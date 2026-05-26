import React from 'react';
import { api, chartUrl } from '../api.js';
import { useApi } from './useApi.js';

function modeTag(mode) {
  if (mode === 'DRONE')  return <span className="tag ok">{mode}</span>;
  if (mode === 'HYBRID') return <span className="tag warn">{mode}</span>;
  return <span className="tag">{mode}</span>;
}

function numFmt(n, digits = 2) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function HybridOperations() {
  const summary = useApi(api.hybridSummary);
  const latency = useApi(api.latency);
  const reasons = useApi(api.activationReasons);

  if (summary.loading || latency.loading || reasons.loading) {
    return <div className="panel muted">Loading hybrid analytics…</div>;
  }
  if (summary.error || latency.error || reasons.error) {
    return (
      <div className="panel error">
        {summary.error || latency.error || reasons.error}
      </div>
    );
  }

  const totals = summary.data?.totals      || {};
  const byScen = summary.data?.by_scenario || [];
  const strat  = latency.data?.strategy_comparison || {};
  const byMode = latency.data?.by_mode || [];
  const reasonCounts = reasons.data?.reason_counts || {};

  if (!totals.orders) return (
    <div className="empty-state">
      No orders or hybrid signals in the DB.  Hybrid fulfillment columns
      populate as part of the default simulation pipeline.  Run:
      <pre className="mono">python run_scenarios.py --trips 100 --seed 42</pre>
    </div>
  );

  return (
    <>
      <div className="panel muted">
        <strong>Note.</strong> <span className="mono">fulfillment_mode</span> is an
        analytical classification — it identifies orders where drone augmentation
        is favorable under the rule set.  It does not claim every order
        physically flew by drone.
      </div>
      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Strategy latency comparison</h2>
        <p className="muted" style={{ margin: '0 0 12px' }}>
          What the average delivery latency would look like if every order
          was sent to trucks, every order was sent to drones, or the hybrid
          activation rules were followed.
        </p>
        <div className="metric-grid">
          <div className="metric">
            <div className="label">Trucks-only avg latency</div>
            <div className="value">{numFmt(strat.trucks_only_avg_latency_min)} min</div>
          </div>
          <div className="metric">
            <div className="label">Drones-only avg latency</div>
            <div className="value">{numFmt(strat.drones_only_avg_latency_min)} min</div>
          </div>
          <div className="metric">
            <div className="label">Hybrid strategy avg latency</div>
            <div className="value">{numFmt(strat.hybrid_strategy_avg_latency_min)} min</div>
          </div>
          <div className="metric">
            <div className="label">Hybrid vs trucks-only savings</div>
            <div className="value numpos">
              {numFmt(strat.hybrid_vs_trucks_only_savings_min)} min
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Fulfillment split by scenario</h2>
        <table>
          <thead>
            <tr>
              <th>scenario</th>
              <th>orders</th>
              <th>truck</th>
              <th>hybrid</th>
              <th>drone</th>
              <th>drone activation</th>
              <th>truck latency (min)</th>
              <th>hybrid latency (min)</th>
              <th>savings (min)</th>
            </tr>
          </thead>
          <tbody>
            {byScen.map((r) => (
              <tr key={r.scenario_name}>
                <td>{r.scenario_name}</td>
                <td className="mono">{numFmt(r.orders, 0)}</td>
                <td className="mono">{numFmt(r.truck_orders, 0)}</td>
                <td className="mono">{numFmt(r.hybrid_orders, 0)}</td>
                <td className="mono">{numFmt(r.drone_orders, 0)}</td>
                <td className="mono">{numFmt(r.drone_activation_pct, 1)} %</td>
                <td className="mono">{numFmt(r.avg_truck_latency_min)}</td>
                <td className="mono">{numFmt(r.avg_hybrid_latency_min)}</td>
                <td className={`mono ${
                  r.hybrid_latency_savings_min >= 0 ? 'numpos' : 'numneg'
                }`}>
                  {numFmt(r.hybrid_latency_savings_min)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Activation reasons</h2>
        <p className="muted" style={{ margin: '0 0 8px' }}>
          How often each rule fired. The first row is usually
          {' '}<span className="mono">heavy_payload</span> — a hard truck
          disqualifier that prevents drone activation regardless of other signals.
        </p>
        <table>
          <thead>
            <tr><th>reason</th><th>fired</th></tr>
          </thead>
          <tbody>
            {Object.entries(reasonCounts).map(([k, v]) => (
              <tr key={k}>
                <td className="mono">{k}</td>
                <td className="mono">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Charts</h2>
        <div className="chart-grid">
          <figure>
            <img src={chartUrl('hybrid_activation_breakdown.png')} alt="hybrid activation breakdown" loading="lazy" />
            <figcaption>hybrid_activation_breakdown.png</figcaption>
          </figure>
          <figure>
            <img src={chartUrl('delivery_latency_by_mode.png')} alt="delivery latency by mode" loading="lazy" />
            <figcaption>delivery_latency_by_mode.png</figcaption>
          </figure>
          <figure>
            <img src={chartUrl('queue_pressure_vs_drone_activation.png')} alt="queue pressure vs drone activation" loading="lazy" />
            <figcaption>queue_pressure_vs_drone_activation.png</figcaption>
          </figure>
        </div>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Per-mode averages</h2>
        <table>
          <thead>
            <tr><th>mode</th><th>orders</th><th>avg latency (min)</th></tr>
          </thead>
          <tbody>
            {byMode.map((r) => (
              <tr key={r.fulfillment_mode}>
                <td>{modeTag(r.fulfillment_mode)}</td>
                <td className="mono">{numFmt(r.orders, 0)}</td>
                <td className="mono">{numFmt(r.avg_latency_min)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
