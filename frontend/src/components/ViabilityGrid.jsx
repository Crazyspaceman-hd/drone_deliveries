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

// Categorical fallbacks — used only when a cell lacks a numeric
// viability_margin (defensive; the API always provides one when
// diagnostics exist).
export const VIABILITY_COLOURS = {
  viable: '#c8e6c9',
  beyond: '#fff59d',
  never:  '#ffcdd2',
};

// Three colour stops for the continuous diverging palette.  Matches the
// matplotlib RdYlGn endpoints used by the published chart so the
// workbench and the README chart read as the same picture.
const PALETTE_STOPS = {
  worst:  [165,  15,  21],   // dark red    #a50f15
  middle: [255, 255, 191],   // pale yellow #ffffbf
  best:   [  0, 104,  55],   // dark green  #006837
};

const NATURAL_CAPACITY_ORDER = [
  'pilot_capacity',
  'regional_capacity',
  'dense_urban_capacity',
];

function _lerp(a, b, t) {
  return [
    Math.round(a[0] + (b[0] - a[0]) * t),
    Math.round(a[1] + (b[1] - a[1]) * t),
    Math.round(a[2] + (b[2] - a[2]) * t),
  ];
}

function _rgb(c) { return `rgb(${c[0]}, ${c[1]}, ${c[2]})`; }

/**
 * Map a viability margin (dollars per delivery, signed) onto a
 * continuous diverging RdYlGn-like palette.  ``maxAbs`` shared across
 * all cells normalises the gradient so positive and negative shades
 * are symmetric and comparable.
 */
export function colourForMargin(margin, maxAbs) {
  if (margin === null || margin === undefined) return '#eeeeee';
  if (!maxAbs || maxAbs <= 0) return _rgb(PALETTE_STOPS.middle);
  // t ∈ [0, 1] where 0 = most negative, 0.5 = neutral, 1 = most positive.
  const t = Math.max(0, Math.min(1, (margin + maxAbs) / (2 * maxAbs)));
  if (t < 0.5) {
    return _rgb(_lerp(PALETTE_STOPS.worst,  PALETTE_STOPS.middle, t * 2));
  }
  return _rgb(_lerp(PALETTE_STOPS.middle, PALETTE_STOPS.best,   (t - 0.5) * 2));
}

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

  const maxAbs = data?.viability_margin_max_abs || 0;

  function cellLabel(c) {
    if (!c) return '—';
    const be   = c.breakeven_deliveries_per_day;
    const ceil = c.addressable_ceiling;
    const m    = c.viability_margin;
    const head = (be === null || be === undefined)
      ? `never\n(ceiling ${ceil}/day)`
      : (be <= ceil)
        ? `≥ ${be}/day\n(ceiling ${ceil}/day)`
        : `breakeven ${be}/day\n(beyond ceiling ${ceil}/day)`;
    if (m === null || m === undefined) return head;
    const sign = m >= 0 ? '+' : '';
    return `${head}\n${sign}$${m.toFixed(2)}/del.`;
  }

  function cellTitle(c) {
    if (!c) return '';
    const be = c.breakeven_deliveries_per_day;
    const m  = c.viability_margin;
    return (
      `${c.capacity_model} × ${c.delivery_domain}\n` +
      `state: ${c.state}\n` +
      `breakeven: ${be === null ? 'never in sweep' : be + ' deliveries/day'}\n` +
      `addressable ceiling: ${c.addressable_ceiling} deliveries/day\n` +
      `viable within addressable demand: ${c.viable_within_addressable_demand ? 'yes' : 'no'}\n` +
      `viability margin at anchor: ${m === null || m === undefined ? 'n/a' : '$' + m.toFixed(2) + '/delivery'}`
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
              {domains.map((d) => {
                // Phase 31: synthetic parameter-sweep variants encode
                // their overrides after '@'.  Show a compact two-line
                // label; the full synthetic name lives in the tooltip.
                const at = d.indexOf('@');
                if (at === -1) return <th key={d} className="mono">{d}</th>;
                return (
                  <th key={d} className="mono" title={`synthetic variant: ${d}`}
                      style={{ fontStyle: 'italic' }}>
                    {d.slice(0, at)}
                    <div className="muted" style={{ fontSize: 10 }}>
                      @{d.slice(at + 1)}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {orderedCaps.map((cap) => {
              // Phase 32: synthetic capacity variants get the same
              // two-line italic treatment as synthetic domain columns.
              const capAt = cap.indexOf('@');
              const capHead = capAt === -1
                ? <th className="mono row-head">{cap}</th>
                : (
                  <th className="mono row-head" title={`synthetic variant: ${cap}`}
                      style={{ fontStyle: 'italic' }}>
                    {cap.slice(0, capAt)}
                    <div className="muted" style={{ fontSize: 10 }}>
                      @{cap.slice(capAt + 1)}
                    </div>
                  </th>
                );
              return (
              <tr key={cap}>
                {capHead}
                {domains.map((dom) => {
                  const c = byCell[`${cap}|${dom}`];
                  // Prefer continuous margin colour; fall back to the
                  // categorical palette only if the cell has no margin
                  // (e.g. diagnostics empty).
                  const colour = c && c.viability_margin !== null && c.viability_margin !== undefined
                    ? colourForMargin(c.viability_margin, maxAbs)
                    : (c ? VIABILITY_COLOURS[c.state] : '#eeeeee');
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
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span>colour = viability margin at addressable anchor ($/delivery):</span>
        </div>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          width: '100%', maxWidth: 480,
        }}>
          <span className="mono">−${maxAbs.toFixed(2)}</span>
          <div style={{
            flex: 1, height: 14,
            background: `linear-gradient(to right, ${colourForMargin(-maxAbs, maxAbs)}, ${colourForMargin(0, maxAbs)}, ${colourForMargin(maxAbs, maxAbs)})`,
            border: '1px solid #ccc',
          }} />
          <span className="mono">+${maxAbs.toFixed(2)}</span>
        </div>
        <p style={{ marginTop: 6 }}>
          Negative = loss depth at the largest sweep point within
          addressable demand. Positive = profit headroom. Cells past the
          ceiling are coloured by their anchor margin (within addressable
          demand) and labelled <em>beyond ceiling</em> textually.
        </p>
      </div>
    </section>
  );
}
