import React from 'react';
import { api } from '../api.js';
import { useApi } from './useApi.js';

/**
 * FailureModes — the "why" companion to the viability grid.
 *
 * The grid above shows WHICH cells fail.  This one explains WHY.  Each
 * non-viable cell carries a diagnostic record anchored at the largest
 * sweep point within its addressable demand: how many drones the model
 * would need, what overhead that produces, what source value sits on
 * the other side of the gap.
 *
 * Aggregate observations sit at the top (one per capacity model that
 * shows a clear pattern); concrete per-cell numbers sit below.
 */
export function FailureModes() {
  const { data, error, loading } = useApi(api.viabilitySummary);
  if (loading) {
    return <div className="panel muted">Computing failure modes…</div>;
  }
  if (error) return <div className="panel error">{error}</div>;

  const pp = data?.pain_points;
  if (!pp || !pp.diagnostics || pp.diagnostics.length === 0) {
    return null;  // nothing to explain
  }

  const observations = pp.observations || [];
  const counts       = pp.constraint_counts || {};
  const diagnostics  = pp.diagnostics || [];
  const nonViable    = diagnostics.filter((d) => d.state !== 'viable');

  // Counts strip — one chip per dominant constraint with non-zero count.
  const constraintEntries = Object.entries(counts).filter(([, n]) => n > 0);

  return (
    <section>
      <h2 className="section-title">Why some cells don't work</h2>
      <p className="muted section-lead">
        The grid above shows which (capacity × domain) cells succeed or
        fail.  This section attributes <em>each</em> non-viable cell to
        its dominant binding constraint, with concrete dollars-per-delivery
        numbers anchored at the largest sweep point within the domain's
        addressable demand.
      </p>

      {constraintEntries.length > 0 && (
        <div className="panel">
          <strong>Dominant constraints across all cells:</strong>{' '}
          {constraintEntries.map(([name, n], i) => (
            <span key={name} style={{ marginLeft: i ? 14 : 8 }}>
              <span className={`tag ${ConstraintBadgeClass[name] || ''}`}>{n}</span>{' '}
              <span className="muted">{ConstraintLabel[name] || name}</span>
            </span>
          ))}
        </div>
      )}

      {observations.length > 0 && (
        <div className="panel">
          <strong>Pattern observations:</strong>
          <ul style={{ margin: '8px 0 0 18px' }}>
            {observations.map((o, i) => (
              <li key={i}>{o.headline}</li>
            ))}
          </ul>
        </div>
      )}

      {nonViable.length > 0 && (
        <>
          <h3 className="section-subtitle">Per-cell diagnostics (non-viable cells)</h3>
          <div className="panel">
            <table>
              <thead>
                <tr>
                  <th>capacity × domain</th>
                  <th>state</th>
                  <th>dominant constraint</th>
                  <th>anchor d</th>
                  <th>required drones</th>
                  <th>overhead $/delivery</th>
                  <th>profit before overhead $/delivery</th>
                  <th>gap $/delivery</th>
                </tr>
              </thead>
              <tbody>
                {nonViable.map((d, i) => (
                  <tr key={`${d.capacity_model}|${d.delivery_domain}|${i}`}>
                    <td className="mono">{d.capacity_model} × {d.delivery_domain}</td>
                    <td><span className={`tag ${StateBadgeClass[d.state] || ''}`}>{d.state}</span></td>
                    <td className="mono">{ConstraintLabel[d.dominant_constraint] || d.dominant_constraint}</td>
                    <td className="mono">{d.anchor_deliveries_per_day ?? '—'}</td>
                    <td className="mono">{d.anchor_required_drones ?? '—'}</td>
                    <td className="mono">{d.anchor_overhead_per_delivery !== null ? `$${d.anchor_overhead_per_delivery.toFixed(2)}` : '—'}</td>
                    <td className="mono">{d.anchor_profit_before_overhead !== null ? `$${d.anchor_profit_before_overhead.toFixed(2)}` : '—'}</td>
                    <td className={`mono ${d.gap_at_anchor !== null && d.gap_at_anchor < 0 ? 'numneg' : 'numpos'}`}>
                      {d.gap_at_anchor !== null
                        ? `${d.gap_at_anchor >= 0 ? '+' : ''}$${d.gap_at_anchor.toFixed(2)}`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            <strong>Anchor</strong> = the largest sweep point at or below the domain's
            addressable-demand ceiling.  This is the deepest the model is
            allowed to look at a cell honestly; anything past the ceiling
            is extrapolation.  <strong>Gap</strong> = effective profit per delivery at
            the anchor (negative = the model never finds break-even
            within addressable demand).
          </p>
        </>
      )}
    </section>
  );
}

const ConstraintLabel = {
  viable:              'viable',
  capacity_overhead:   'capacity overhead exceeds source profit',
  addressable_demand:  'addressable demand caps out before break-even',
  mixed:               'mixed',
  no_data:             '(no data)',
};

const ConstraintBadgeClass = {
  viable:              'ok',
  capacity_overhead:   'err',
  addressable_demand:  'warn',
  mixed:               '',
  no_data:             '',
};

const StateBadgeClass = {
  viable: 'ok',
  beyond: 'warn',
  never:  'err',
};
