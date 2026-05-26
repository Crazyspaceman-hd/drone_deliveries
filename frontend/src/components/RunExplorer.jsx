import React, { useState } from 'react';
import { api } from '../api.js';
import { useApi } from './useApi.js';

/**
 * Run explorer: list of simulation_runs + flat per-run lineage table
 * showing every transformation_runs row tied to that source.  No graph
 * viz — a flat table is the most reviewer-legible shape.
 */
export function RunExplorer() {
  const { data, error, loading } = useApi(api.runs);
  const [selectedId, setSelectedId] = useState(null);

  if (loading) return <div className="panel muted">Loading runs…</div>;
  if (error)   return <div className="panel error">{error}</div>;
  const runs = data?.runs || [];
  if (!runs.length) return (
    <div className="empty-state">
      No simulation runs recorded yet.  Try:
      <pre className="mono">python run_scenarios.py --reset --trips 50 --seed 42</pre>
    </div>
  );

  const activeId = selectedId ?? runs[0].run_id;

  return (
    <div>
      <p className="muted section-lead">
        Every simulator invocation writes one <span className="mono">simulation_runs</span> row.
        Click a row to see the transforms that ran against it.
      </p>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>run_id</th>
              <th>created_at</th>
              <th>scenario</th>
              <th>seed</th>
              <th>trips</th>
              <th>drones</th>
              <th>sim</th>
              <th>assumptions</th>
              <th>git</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr
                key={r.run_id}
                className={r.run_id === activeId ? 'row-selected' : ''}
                onClick={() => setSelectedId(r.run_id)}
                style={{ cursor: 'pointer' }}
              >
                <td className="mono">{r.run_id.slice(0, 8)}…</td>
                <td className="mono">{(r.created_at || '').slice(0, 19)}</td>
                <td>{r.scenario_names || '—'}</td>
                <td>{r.seed}</td>
                <td>{r.trip_count}</td>
                <td>{r.drone_count}</td>
                <td className="mono">{r.simulator_version}</td>
                <td className="mono">{r.assumption_version}</td>
                <td className="mono">{(r.git_commit || '—').slice(0, 8)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <LineageTable runId={activeId} />
    </div>
  );
}

function LineageTable({ runId }) {
  const { data, error, loading } = useApi(
    () => api.runTransforms(runId), [runId]
  );
  if (loading) return <div className="panel muted">Loading lineage…</div>;
  if (error)   return <div className="panel error">{error}</div>;
  const rows = data?.transforms || [];
  return (
    <section>
      <h3 className="section-subtitle">
        Transform lineage{' '}
        <span className="muted mono">({runId.slice(0, 8)}…)</span>
      </h3>
      {!rows.length ? (
        <div className="empty-state">
          No transforms run against this source.  Try:
          <pre className="mono">python run_transforms.py --all-runs</pre>
        </div>
      ) : (
        <div className="panel">
          <table className="lineage-table">
            <thead>
              <tr>
                <th>transform_name</th>
                <th>version</th>
                <th>created_at</th>
                <th>rows</th>
                <th>parameters</th>
                <th>experiment</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.transform_run_id}>
                  <td className="mono">{r.transform_name}</td>
                  <td className="mono">{r.transform_version}</td>
                  <td className="mono">{(r.created_at || '').slice(0, 19)}</td>
                  <td className="mono">{r.row_count ?? '—'}</td>
                  <td className="mono params-cell" title={r.parameters_json || ''}>
                    {(r.parameters_json || '').slice(0, 80)}
                    {(r.parameters_json || '').length > 80 ? '…' : ''}
                  </td>
                  <td className="mono">
                    {r.experiment_run_id ? r.experiment_run_id.slice(0, 8) + '…' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
