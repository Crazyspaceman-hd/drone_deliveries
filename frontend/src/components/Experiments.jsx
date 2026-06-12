import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api.js';
import { useApi } from './useApi.js';
import { WhatIfLauncher } from './WhatIfLauncher.jsx';
import { ParameterGridExplorer } from './ParameterGridExplorer.jsx';

/**
 * Experiment lineage browser (Phase 24 orchestration layer).  Two views:
 *   /experiments        — list
 *   /experiments/:id    — detail with summary.profiles matrix
 */

export function ExperimentsList() {
  const { data, error, loading } = useApi(api.experiments);
  const exps = data?.experiments || [];
  return (
    <div>
      {/* Phase 32: the what-if launcher (1-D, feeds the main viability
          grid) and the two-parameter explorer (2-D, self-contained
          heatmap) are both always available, even before any experiment
          exists. */}
      <WhatIfLauncher />
      <ParameterGridExplorer />

      {loading && <div className="panel muted">Loading experiments…</div>}
      {error   && <div className="panel error">{error}</div>}
      {!loading && !error && !exps.length && (
        <div className="empty-state">
          No experiments recorded yet.  Launch one above, or from the CLI:
          <pre className="mono">{`python run_experiment.py --list
python run_experiment.py --name pilot_operator_ratio_sensitivity`}</pre>
        </div>
      )}
      {!!exps.length && <ExperimentsTable exps={exps} />}
    </div>
  );
}

function ExperimentsTable({ exps }) {
  return (
    <div>
      <p className="muted section-lead">
        Experiments are named Cartesian sweeps of analytical knobs over
        existing simulation runs.  Each row links to its full
        (scenario × domain × scale) profile matrix.
      </p>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>name</th>
              <th>experiment_run_id</th>
              <th>status</th>
              <th>started_at</th>
              <th>completed_at</th>
            </tr>
          </thead>
          <tbody>
            {exps.map((e) => (
              // Ad-hoc CLI sweeps (--sweep) get muted styling: kept in
              // the audit trail but visually distinct from named runs.
              <tr key={e.experiment_run_id}
                  style={e.experiment_name?.startsWith('_adhoc_')
                    ? { opacity: 0.55, fontStyle: 'italic' } : undefined}>
                <td className="mono">
                  <Link to={`/experiments/${e.experiment_run_id}`}>
                    {e.experiment_name}
                  </Link>
                </td>
                <td className="mono">{e.experiment_run_id.slice(0, 8)}…</td>
                <td><StatusBadge status={e.status} /></td>
                <td className="mono">{(e.started_at || '').slice(0, 19)}</td>
                <td className="mono">{(e.completed_at || '').slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ExperimentDetail() {
  const { id } = useParams();
  const { data, error, loading } = useApi(() => api.experiment(id), [id]);
  if (loading) return <div className="panel muted">Loading experiment…</div>;
  if (error)   return <div className="panel error">{error}</div>;
  if (!data)   return <div className="panel muted">Not found.</div>;
  return (
    <div>
      <p>
        <Link to="/experiments">← All experiments</Link>
      </p>
      <section className="panel">
        <h2 className="section-title">{data.experiment_name}</h2>
        <table className="kv">
          <tbody>
            <tr><td className="muted">experiment_run_id</td>
                <td className="mono">{data.experiment_run_id}</td></tr>
            <tr><td className="muted">status</td>
                <td><StatusBadge status={data.status} /></td></tr>
            <tr><td className="muted">started_at</td>
                <td className="mono">{data.started_at}</td></tr>
            <tr><td className="muted">completed_at</td>
                <td className="mono">{data.completed_at || '—'}</td></tr>
          </tbody>
        </table>
        {data.error && (
          <p className="error mono">Error: {data.error}</p>
        )}
      </section>

      <DefinitionPanel def={data.definition} />
      <ProfilesTable profiles={data.summary?.profiles || []} />
    </div>
  );
}

function StatusBadge({ status }) {
  const cls = status === 'completed' ? 'ok'
            : status === 'failed'    ? 'err'
            : 'warn';
  return <span className={`tag ${cls}`}>{status}</span>;
}

function DefinitionPanel({ def }) {
  if (!def) return null;
  return (
    <section className="panel">
      <h3 className="section-subtitle">Definition</h3>
      <table className="kv">
        <tbody>
          {Object.entries(def).map(([k, v]) => (
            <tr key={k}>
              <td className="muted">{k}</td>
              <td className="mono">{Array.isArray(v) ? v.join(', ') || '(all)' : String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ProfilesTable({ profiles }) {
  if (!profiles.length) return (
    <div className="empty-state">
      No profile rows yet — experiment may have failed or not produced
      snapshots.
    </div>
  );
  return (
    <section>
      <h3 className="section-subtitle">Summary profiles</h3>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>scenario</th>
              <th>domain</th>
              <th>scale</th>
              <th>avg revenue</th>
              <th>avg overhead</th>
              <th>avg effective profit</th>
              <th>break-even rate</th>
              <th>trips</th>
            </tr>
          </thead>
          <tbody>
            {profiles.map((p, i) => (
              <tr key={`${p.scenario_name}|${p.domain_name}|${p.scale_model_name}|${i}`}>
                <td className="mono">{p.scenario_name}</td>
                <td className="mono">{p.domain_name}</td>
                <td className="mono">{p.scale_model_name}</td>
                <td className="mono">${p.avg_revenue?.toFixed(2)}</td>
                <td className="mono">${p.avg_overhead?.toFixed(2)}</td>
                <td className={`mono ${p.avg_effective_profit >= 0 ? 'numpos' : 'numneg'}`}>
                  ${p.avg_effective_profit?.toFixed(2)}
                </td>
                <td className="mono">{((p.break_even_rate ?? 0) * 100).toFixed(0)}%</td>
                <td className="mono">{p.trip_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
