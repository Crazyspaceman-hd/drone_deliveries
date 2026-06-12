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

  const costCounts = pp.dominant_cost_counts || {};
  const costEntries = Object.entries(costCounts).filter(([, n]) => n > 0);

  return (
    <section>
      <h2 className="section-title">Why some cells don't work</h2>
      <p className="muted section-lead">
        The grid above shows which (capacity × domain) cells succeed or
        fail.  This section attributes <em>each</em> non-viable cell to
        its dominant binding constraint AND to the dominant component of
        capacity overhead, with concrete dollars-per-delivery numbers
        anchored at the largest sweep point within the domain's
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

      {costEntries.length > 0 && (
        <div className="panel">
          <strong>Dominant cost component across failing cells:</strong>{' '}
          {costEntries.map(([name, n], i) => (
            <span key={name} style={{ marginLeft: i ? 14 : 8 }}>
              <span className="tag err">{n}</span>{' '}
              <span className="muted">{CostComponentLabel[name] || name}</span>
            </span>
          ))}
          <p className="muted" style={{ marginTop: 6, fontSize: 12 }}>
            The capacity-overhead total is the sum of five components:
            platform fixed cost, drone leases, operator wages, maintenance
            staff, chargers. The histogram above tells you which one is
            doing the most damage. The lever to fix a failing cell is
            the CapacityModel field behind the dominant component — not
            "less overhead" in the abstract.
          </p>
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
                  <th>anchor d</th>
                  <th>drones</th>
                  <th>overhead $/del.</th>
                  <th>profit pre-overhead $/del.</th>
                  <th>gap $/del.</th>
                  <th>dominant cost</th>
                </tr>
              </thead>
              <tbody>
                {nonViable.map((d, i) => {
                  const bd = d.cost_breakdown_at_anchor || {};
                  const breakdownTip = Object.entries(bd)
                    .map(([k, v]) => `  ${CostComponentLabel[k] || k}: $${v.toFixed(2)}/del.`)
                    .join('\n');
                  const dom = d.dominant_cost_component;
                  const domValue = dom && bd[dom] !== undefined ? bd[dom] : null;
                  const share = d.dominant_cost_share != null
                    ? Math.round(d.dominant_cost_share * 100) : null;
                  return (
                    <tr key={`${d.capacity_model}|${d.delivery_domain}|${i}`}>
                      <td className="mono">{d.capacity_model} × {d.delivery_domain}</td>
                      <td><span className={`tag ${StateBadgeClass[d.state] || ''}`}>{d.state}</span></td>
                      <td className="mono">{d.anchor_deliveries_per_day ?? '—'}</td>
                      <td className="mono">{d.anchor_required_drones ?? '—'}</td>
                      <td className="mono"
                          title={`Overhead breakdown ($/delivery):\n${breakdownTip}`}>
                        {d.anchor_overhead_per_delivery !== null
                          ? `$${d.anchor_overhead_per_delivery.toFixed(2)}` : '—'}
                      </td>
                      <td className="mono">
                        {d.anchor_profit_before_overhead !== null
                          ? `$${d.anchor_profit_before_overhead.toFixed(2)}` : '—'}
                      </td>
                      <td className={`mono ${d.gap_at_anchor !== null && d.gap_at_anchor < 0 ? 'numneg' : 'numpos'}`}>
                        {d.gap_at_anchor !== null
                          ? `${d.gap_at_anchor >= 0 ? '+' : ''}$${d.gap_at_anchor.toFixed(2)}`
                          : '—'}
                      </td>
                      <td className="mono"
                          title={`Five-component breakdown at this anchor:\n${breakdownTip}`}>
                        {dom
                          ? <>{CostComponentLabel[dom] || dom}{' '}
                              <span className="muted">
                                ({share != null ? `${share}%` : '—'}
                                {domValue != null ? `, $${domValue.toFixed(2)}/del.` : ''})
                              </span>
                            </>
                          : '—'}
                      </td>
                    </tr>
                  );
                })}
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

// Short, plain-English labels for the five CapacityModel cost
// components.  Keep these in sync with COST_COMPONENTS in
// core/portfolio_summary.py.
const CostComponentLabel = {
  platform_fixed:  'platform fixed',
  drone_leases:    'drone leases',
  operator_wages:  'operator wages',
  maintenance:     'maintenance staff',
  chargers:        'chargers',
};
