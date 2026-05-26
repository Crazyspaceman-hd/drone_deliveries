import React from 'react';
import { api } from '../api.js';
import { useApi } from './useApi.js';

function labelTag(label) {
  if (label === 'strong_candidate') return <span className="tag ok">{label}</span>;
  if (label === 'borderline')       return <span className="tag warn">{label}</span>;
  return <span className="tag err">{label}</span>;
}

export function ScenarioComparison() {
  const { data, error, loading } = useApi(api.scenariosSummary);
  if (loading) return <div className="panel muted">Loading scenarios…</div>;
  if (error)   return <div className="panel error">{error}</div>;

  const bi    = data?.bi_rankings || [];
  const calib = data?.calibration || [];
  // Index calibration by scenario_name for the joined table.
  const cByScen = Object.fromEntries(
    calib.map((r) => [r.scenario_name, r]),
  );

  return (
    <>
      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>BI feasibility ranking</h2>
        <table>
          <thead>
            <tr>
              <th>scenario</th>
              <th>score</th>
              <th>label</th>
              <th>completion</th>
              <th>avg profit / trip</th>
              <th>emerg rate</th>
              <th>maint / trip</th>
            </tr>
          </thead>
          <tbody>
            {bi.map((r) => (
              <tr key={r.scenario_name}>
                <td>{r.scenario_name}</td>
                <td className="mono">{r.feasibility_score}</td>
                <td>{labelTag(r.feasibility_label)}</td>
                <td className="mono">{r.completion_rate}</td>
                <td className={`mono ${r.avg_profit_per_trip >= 0 ? 'numpos' : 'numneg'}`}>
                  {r.avg_profit_per_trip}
                </td>
                <td className="mono">{r.emergency_rate}</td>
                <td className="mono">{r.maintenance_per_trip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>Calibration drift</h2>
        <table>
          <thead>
            <tr>
              <th>scenario</th>
              <th>cfg emerg</th>
              <th>obs emerg</th>
              <th>cfg dist (km)</th>
              <th>obs dist (km)</th>
              <th>dist drift (km)</th>
              <th>distance label</th>
            </tr>
          </thead>
          <tbody>
            {bi.map((r) => {
              const c = cByScen[r.scenario_name] || {};
              return (
                <tr key={r.scenario_name}>
                  <td>{r.scenario_name}</td>
                  <td className="mono">{c.configured_emergency_return_chance ?? '—'}</td>
                  <td className="mono">{c.observed_emergency_return_rate    ?? '—'}</td>
                  <td className="mono">{c.configured_avg_trip_distance_km   ?? '—'}</td>
                  <td className="mono">{c.observed_avg_trip_distance_km     ?? '—'}</td>
                  <td className="mono">{c.avg_trip_distance_drift_km        ?? '—'}</td>
                  <td>{c.avg_trip_distance_drift_label
                        ? <span className="tag">{c.avg_trip_distance_drift_label}</span>
                        : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
