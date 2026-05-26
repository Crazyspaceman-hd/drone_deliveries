import React from 'react';
import { api } from '../api.js';
import { useApi } from './useApi.js';

function sevTag(sev) {
  if (sev === 'ERROR') return <span className="tag err">ERROR</span>;
  if (sev === 'WARN')  return <span className="tag warn">WARN</span>;
  return <span className="tag">INFO</span>;
}

export function ValidationPanel() {
  const { data, error, loading } = useApi(api.validation);
  if (loading) return <div className="panel muted">Running checks…</div>;
  if (error)   return <div className="panel error">{error}</div>;
  const { results = [], counts_by_severity, failed_by_severity, any_errors } = data || {};
  if (!results.length) return (
    <div className="empty-state">
      No validation results.  Run:
      <pre className="mono">python run_validation.py</pre>
    </div>
  );
  // Failed rules first; within each pass/fail group, ERROR before WARN before INFO.
  const sevRank = { ERROR: 0, WARN: 1, INFO: 2 };
  const sorted  = [...results].sort((a, b) => {
    if (a.passed !== b.passed) return a.passed ? 1 : -1;
    return (sevRank[a.severity] ?? 9) - (sevRank[b.severity] ?? 9);
  });
  return (
    <>
      <p className="muted section-lead">
        Rule-based validation across snapshot tables.  Each rule asserts a
        structural invariant — e.g. every trip has economics, no scale
        snapshot is orphaned from a transformation_runs row.  Passing means
        the data engineering pipeline produced internally consistent
        derived state, not that the analytical numbers are realistic.
      </p>
      <div className="panel">
        <div className="metric-grid">
          <div className="metric">
            <div className="label">Total checks</div>
            <div className="value">{Object.values(counts_by_severity || {}).reduce((a, b) => a + b, 0)}</div>
          </div>
          <div className="metric">
            <div className="label">ERROR failures</div>
            <div className="value" style={{ color: 'var(--err)' }}>
              {failed_by_severity?.ERROR ?? 0}
            </div>
          </div>
          <div className="metric">
            <div className="label">WARN failures</div>
            <div className="value" style={{ color: 'var(--warn)' }}>
              {failed_by_severity?.WARN ?? 0}
            </div>
          </div>
          <div className="metric">
            <div className="label">Overall</div>
            <div className="value">
              {any_errors
                ? <span className="tag err">ERRORS PRESENT</span>
                : <span className="tag ok">no errors</span>}
            </div>
          </div>
        </div>
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>rule</th><th>severity</th><th>passed</th>
              <th>run</th><th>details</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={i}>
                <td className="mono">{r.rule_name}</td>
                <td>{sevTag(r.severity)}</td>
                <td>
                  {r.passed
                    ? <span className="tag ok">yes</span>
                    : <span className="tag err">NO</span>}
                </td>
                <td className="mono">{(r.run_id || '').slice(0, 8) || '—'}</td>
                <td>{r.details}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
