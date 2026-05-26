import React from 'react';
import { api, chartUrl } from '../api.js';
import { useApi } from './useApi.js';

function numFmt(n, d = 2) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: d });
}

export function OperationalTelemetry() {
  const summary = useApi(api.telemetrySummary);
  const health  = useApi(api.telemetryHealth);

  if (summary.loading || health.loading) {
    return <div className="panel muted">Loading telemetry…</div>;
  }
  if (summary.error || health.error) {
    return <div className="panel error">{summary.error || health.error}</div>;
  }

  const byScen   = summary.data?.by_scenario || [];
  const anom     = health.data?.anomalies_by_scenario || [];
  const drones   = health.data?.drone_health || [];

  // Signal-quality metric grid: aggregate avg signal + avg gps across scenarios.
  const totalPings = byScen.reduce((s, r) => s + (r.pings || 0), 0);
  const weightedSig = totalPings
    ? byScen.reduce((s, r) => s + (r.avg_signal_pct || 0) * (r.pings || 0), 0) / totalPings
    : 0;
  const weightedGps = totalPings
    ? byScen.reduce((s, r) => s + (r.avg_gps_quality || 0) * (r.pings || 0), 0) / totalPings
    : 0;
  const totalSignalWeak = anom.reduce((s, r) => s + (r.signal_weak_count || 0), 0);
  const totalGpsDeg     = anom.reduce((s, r) => s + (r.gps_degraded_count || 0), 0);

  return (
    <>
      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Signal quality</h2>
        <p className="muted" style={{ margin: '0 0 12px' }}>
          Aggregated across all telemetry pings in the current database.
        </p>
        <div className="metric-grid">
          <div className="metric">
            <div className="label">Total telemetry pings</div>
            <div className="value">{numFmt(totalPings, 0)}</div>
          </div>
          <div className="metric">
            <div className="label">Avg signal strength</div>
            <div className="value">{numFmt(weightedSig)} %</div>
          </div>
          <div className="metric">
            <div className="label">Avg GPS quality</div>
            <div className="value">{numFmt(weightedGps)}</div>
          </div>
          <div className="metric">
            <div className="label">Signal weak / GPS degraded</div>
            <div className="value">
              {numFmt(totalSignalWeak, 0)} / {numFmt(totalGpsDeg, 0)}
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Anomalies by scenario</h2>
        <table>
          <thead>
            <tr>
              <th>scenario</th>
              <th>battery hot (&gt;50°C)</th>
              <th>motor hot (&gt;85°C)</th>
              <th>signal weak (&lt;60%)</th>
              <th>gps degraded (&lt;60)</th>
              <th>obstacle warnings</th>
            </tr>
          </thead>
          <tbody>
            {anom.map((r) => (
              <tr key={r.scenario_name}>
                <td>{r.scenario_name}</td>
                <td className="mono">{numFmt(r.battery_hot_count, 0)}</td>
                <td className="mono">{numFmt(r.motor_hot_count, 0)}</td>
                <td className="mono">{numFmt(r.signal_weak_count, 0)}</td>
                <td className="mono">{numFmt(r.gps_degraded_count, 0)}</td>
                <td className="mono">{numFmt(r.obstacle_warning_count, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Drone health (slowly-changing)</h2>
        <table>
          <thead>
            <tr>
              <th>drone</th>
              <th>status</th>
              <th>battery cycles</th>
              <th>battery health</th>
            </tr>
          </thead>
          <tbody>
            {drones.map((d) => (
              <tr key={d.drone_id}>
                <td className="mono">{d.drone_id}</td>
                <td>{d.status}</td>
                <td className="mono">{numFmt(d.battery_cycle_count, 0)}</td>
                <td className="mono">{numFmt(d.battery_health_pct)} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Charts</h2>
        <div className="chart-grid">
          <figure>
            <img src={chartUrl('battery_temperature_by_scenario.png')}
                 alt="battery temperature by scenario" loading="lazy" />
            <figcaption>battery_temperature_by_scenario.png</figcaption>
          </figure>
          <figure>
            <img src={chartUrl('signal_quality_distribution.png')}
                 alt="signal quality distribution" loading="lazy" />
            <figcaption>signal_quality_distribution.png</figcaption>
          </figure>
        </div>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Per-scenario averages</h2>
        <table>
          <thead>
            <tr>
              <th>scenario</th><th>pings</th>
              <th>avg altitude (m)</th><th>avg airspeed (m/s)</th>
              <th>avg battery °C</th><th>max battery °C</th>
              <th>avg motor °C</th><th>max motor °C</th>
              <th>avg signal %</th><th>avg gps</th><th>avg range (km)</th>
            </tr>
          </thead>
          <tbody>
            {byScen.map((r) => (
              <tr key={r.scenario_name}>
                <td>{r.scenario_name}</td>
                <td className="mono">{numFmt(r.pings, 0)}</td>
                <td className="mono">{numFmt(r.avg_altitude_m)}</td>
                <td className="mono">{numFmt(r.avg_airspeed_mps)}</td>
                <td className="mono">{numFmt(r.avg_battery_temp_c)}</td>
                <td className="mono">{numFmt(r.max_battery_temp_c)}</td>
                <td className="mono">{numFmt(r.avg_motor_temp_c)}</td>
                <td className="mono">{numFmt(r.max_motor_temp_c)}</td>
                <td className="mono">{numFmt(r.avg_signal_pct)}</td>
                <td className="mono">{numFmt(r.avg_gps_quality)}</td>
                <td className="mono">{numFmt(r.avg_remaining_range_km, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
