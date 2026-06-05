import React from 'react';
import { api } from '../api.js';
import { useApi } from './useApi.js';

/**
 * ViabilityGrid — the headline answer card.
 *
 * Renders a (capacity_model × delivery_domain) grid coloured by
 * viability state.  Shared across the Overview, Main Finding, and
 * Domain & Scale pages so the same answer is visible everywhere a
 * reviewer might land.
 *
 *   - green  (viable)  = breakeven sits within addressable demand
 *   - yellow (beyond)  = breakeven exists but only past the ceiling
 *   - red    (never)   = no sweep point clears zero
 */

export const VIABILITY_COLOURS = {
  viable: '#c8e6c9',
  beyond: '#fff59d',
  never:  '#ffcdd2',
};

const NATURAL_CAPACITY_ORDER = [
  'pilot_capacity',
  'regional_capacity',
  'dense_urban_capacity',
];

export function ViabilityGrid({ showTitle = true } = {}) {
  const { data, error, loading } = useApi(api.viabilitySummary);
  if (loading) {
    return <div className="panel muted">Computing viability summary…</div>;
  }
  if (error) return <div className="panel error">{error}</div>;
  const cells   = data?.cells           || [];
  const caps    = data?.capacity_models || [];
  const domains = data?.delivery_domains || [];

  if (!cells.length) {
    return (
      <div className="empty-state">
        No economics snapshots available — viability summary needs at
        least one domain populated:
        <pre className="mono">{`python run_transforms.py --all-runs
python run_transforms.py --all-runs --all-delivery-domains`}</pre>
      </div>
    );
  }

  const orderedCaps = [
    ...NATURAL_CAPACITY_ORDER.filter((c) => caps.includes(c)),
    ...caps.filter((c) => !NATURAL_CAPACITY_ORDER.includes(c)),
  ];

  const byCell = {};
  for (const c of cells) {
    byCell[`${c.capacity_model}|${c.delivery_domain}`] = c;
  }

  function cellLabel(c) {
    if (!c) return '—';
    const be   = c.breakeven_deliveries_per_day;
    const ceil = c.addressable_ceiling;
    if (be === null || be === undefined) return `never\n(ceiling ${ceil}/day)`;
    if (be <= ceil) return `≥ ${be}/day\n(ceiling ${ceil}/day)`;
    return `breakeven ${be}/day\n(beyond ceiling ${ceil}/day)`;
  }

  function cellTitle(c) {
    if (!c) return '';
    const be = c.breakeven_deliveries_per_day;
    return (
      `${c.capacity_model} × ${c.delivery_domain}\n` +
      `state: ${c.state}\n` +
      `breakeven: ${be === null ? 'never in sweep' : be + ' deliveries/day'}\n` +
      `addressable ceiling: ${c.addressable_ceiling} deliveries/day\n` +
      `viable within addressable demand: ${c.viable_within_addressable_demand ? 'yes' : 'no'}`
    );
  }

  return (
    <section>
      {showTitle && <h2 className="section-title">Viability summary</h2>}
      {showTitle && (
        <p className="muted section-lead">
          For every <span className="mono">(capacity_model × delivery_domain)</span> cell:
          does the synthetic model find a sweep point where effective profit
          per delivery clears zero, and does that point sit inside the
          domain's addressable-demand ceiling?
        </p>
      )}

      <div className="panel matrix-wrap">
        <table className="matrix-table">
          <thead>
            <tr>
              <th>capacity model ↓ / domain →</th>
              {domains.map((d) => <th key={d} className="mono">{d}</th>)}
            </tr>
          </thead>
          <tbody>
            {orderedCaps.map((cap) => (
              <tr key={cap}>
                <th className="mono row-head">{cap}</th>
                {domains.map((dom) => {
                  const c = byCell[`${cap}|${dom}`];
                  const colour = c ? VIABILITY_COLOURS[c.state] : '#eeeeee';
                  return (
                    <td
                      key={dom}
                      title={cellTitle(c)}
                      style={{
                        backgroundColor: colour,
                        whiteSpace: 'pre-line',
                        textAlign: 'center',
                        fontSize: 12,
                      }}
                    >
                      {cellLabel(c)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted" style={{ fontSize: 12 }}>
        <span style={{ background: VIABILITY_COLOURS.viable, padding: '2px 8px', marginRight: 6 }}>green</span>
        viable within addressable demand   ·{' '}
        <span style={{ background: VIABILITY_COLOURS.beyond, padding: '2px 8px', margin: '0 6px' }}>yellow</span>
        breakeven exists but only past the ceiling   ·{' '}
        <span style={{ background: VIABILITY_COLOURS.never, padding: '2px 8px', margin: '0 6px' }}>red</span>
        no breakeven in sweep
      </p>
    </section>
  );
}
