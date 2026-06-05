import React from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api.js';
import { useApi } from './useApi.js';
import { ViabilityGrid } from './ViabilityGrid.jsx';

/**
 * Decision summary.  Each finding card is rule-based, derived from one
 * deterministic endpoint output.  No LLM prose.  Each card has three
 * states: loading, empty (with reproduction command), populated.
 */
export function MainFinding() {
  const disp     = useApi(() => api.displacement());
  const latency  = useApi(api.latency);
  const matrix   = useApi(api.domainScaleMatrix);
  const validate = useApi(api.validation);
  // domains/scales were consumed by the deprecated DomainCard /
  // ScaleCard rendered above; the ViabilityGrid subsumes both and
  // makes the network requests unnecessary on this page.  The
  // components themselves still exist in this file for reuse.

  return (
    <div>
      <p className="muted section-lead">
        The viability grid below is the primary signal.  For every
        <span className="mono"> (capacity_model × delivery_domain) </span>
        cell, it asks whether the model finds break-even and whether
        that break-even sits inside the domain's addressable demand.
        The supporting cards underneath surface the numbers behind one
        slice of the story — operational cost vs trucks, hybrid latency,
        and validation status.
      </p>

      <ViabilityGrid showTitle={false} />

      <p className="muted">
        For the full grid + line-chart small multiples + per-volume
        breakdown, see <Link to="/domain-scale">Domain &amp; Scale</Link>.
      </p>

      <h2 className="section-title">Supporting cards</h2>
      <div className="finding-grid">
        <OperationalVsTrucksCard disp={disp} matrix={matrix} />
        <HybridLatencyCard call={latency} />
        <ValidationCard call={validate} />
      </div>

      <p className="muted">
        For the underlying tables, see{' '}
        <Link to="/domain-scale">Domain &amp; Scale</Link>,{' '}
        <Link to="/hybrid">Hybrid</Link>, and{' '}
        <Link to="/validation">Validation</Link>.
      </p>
    </div>
  );
}

// ── individual finding cards ────────────────────────────────────────────────

function Card({ title, children, status }) {
  const klass = status ? `finding-card ${status}` : 'finding-card';
  return (
    <div className={klass}>
      <h3 className="finding-title">{title}</h3>
      {children}
    </div>
  );
}

function CardLoading({ title }) {
  return <Card title={title}><p className="muted">Loading…</p></Card>;
}

function CardEmpty({ title, command }) {
  return (
    <Card title={title}>
      <p className="muted">No data yet.</p>
      <pre className="mono empty-cmd">{command}</pre>
    </Card>
  );
}

function CardError({ title, error }) {
  return <Card title={title} status="err"><p className="error">{error}</p></Card>;
}

function OperationalVsTrucksCard({ disp, matrix }) {
  const title = 'Operational cost vs trucks';
  if (disp.loading) return <CardLoading title={title} />;
  if (disp.error)   return <CardError title={title} error={disp.error} />;
  const t = disp.data?.totals;
  if (!t || !t.completed_drone_deliveries) return <CardEmpty title={title}
    command={'python run_scenarios.py --scenarios suburban_standard --trips 100 --seed 42'} />;

  // Deterministic break-even: at what per-delivery truck cost does the
  // aggregate flip from drone-favored to truck-favored?
  const completed   = t.completed_drone_deliveries;
  const dronePer    = t.estimated_drone_operational_cost / completed;
  const truckPer    = t.estimated_truck_delivery_cost     / completed;
  const breakEven   = dronePer;            // by construction
  const diffAgg     = t.estimated_cost_difference;

  // Pull the cell distribution from the matrix endpoint.  This is the
  // information the headline aggregate hides: of all (scenario × domain
  // × scale) cells we computed, how many actually clear overhead?
  const cells      = matrix.data?.cells || [];
  const profitable = cells.filter((c) => c.avg_effective_profit > 0).length;
  const total      = cells.length;
  const profPct    = total ? Math.round((profitable / total) * 100) : null;

  // Deliberately neutral / "warn".  Operational-only is never the right
  // thing to celebrate green — the matrix tells the real story.
  return (
    <Card title={title} status="warn">
      <p className="finding-headline">
        Drone operational cost: ${dronePer.toFixed(2)} per completed delivery.
      </p>
      <p className="muted">
        Operational only — no fleet overhead, no demand variance.  Whether
        that beats trucks depends entirely on which truck-cost number you
        believe, and what (domain × scale) cell you're standing in.
      </p>
      <table className="kv">
        <tbody>
          <tr><td className="muted">Drone op cost / delivery</td>
              <td className="mono">${dronePer.toFixed(2)}</td></tr>
          <tr><td className="muted">Truck-cost break-even</td>
              <td className="mono">${breakEven.toFixed(2)}</td></tr>
          <tr><td className="muted">Default truck assumption</td>
              <td className="mono">${truckPer.toFixed(2)}</td></tr>
          <tr><td className="muted">Aggregate at default</td>
              <td className={`mono ${diffAgg > 0 ? 'numpos' : 'numneg'}`}>
                {diffAgg > 0 ? '+' : ''}${diffAgg.toFixed(2)}
              </td></tr>
          <tr><td className="muted">Completed drone deliveries</td>
              <td className="mono">{completed}</td></tr>
        </tbody>
      </table>
      {total > 0 ? (
        <p className="muted">
          Under the full unit-economics view, <strong>{profitable} of {total}</strong>
          {' '}(domain × scale) cells produce positive effective profit ({profPct}%).
          The aggregate above ignores that distribution — see{' '}
          <Link to="/domain-scale">Domain &amp; Scale</Link>.
        </p>
      ) : (
        <p className="muted">
          Run the domain + scale transforms to populate the per-cell
          breakdown.  See <Link to="/domain-scale">Domain &amp; Scale</Link>.
        </p>
      )}
    </Card>
  );
}

function HybridLatencyCard({ call }) {
  const title = 'Hybrid augmentation latency';
  if (call.loading) return <CardLoading title={title} />;
  if (call.error)   return <CardError title={title} error={call.error} />;
  const s = call.data?.strategy_comparison;
  if (!s) return <CardEmpty title={title}
    command={'python run_scenarios.py --trips 100 --seed 42  # hybrid columns are populated by the default sim run'} />;
  const improvement = (s.trucks_only_avg_latency_min - s.hybrid_strategy_avg_latency_min);
  const better = improvement > 0;
  return (
    <Card title={title} status={better ? 'ok' : 'warn'}>
      <p className="finding-headline">
        {better
          ? `Hybrid strategy improves average latency by ${improvement.toFixed(1)} min vs trucks-only.`
          : `Hybrid strategy does not improve latency vs trucks-only.`}
      </p>
      <table className="kv">
        <tbody>
          <tr><td className="muted">Trucks-only avg</td>
              <td className="mono">{s.trucks_only_avg_latency_min?.toFixed(1)} min</td></tr>
          <tr><td className="muted">Hybrid avg</td>
              <td className="mono">{s.hybrid_strategy_avg_latency_min?.toFixed(1)} min</td></tr>
          <tr><td className="muted">Drones-only avg</td>
              <td className="mono">{s.drones_only_avg_latency_min?.toFixed(1)} min</td></tr>
        </tbody>
      </table>
    </Card>
  );
}

function DomainCard({ call }) {
  const title = 'Best delivery domain';
  if (call.loading) return <CardLoading title={title} />;
  if (call.error)   return <CardError title={title} error={call.error} />;
  const snaps = call.data?.latest_snapshots || [];
  if (!snaps.length) return <CardEmpty title={title}
    command={'python run_transforms.py --all-runs --all-delivery-domains'} />;
  // Average profit per domain, ranked.
  const byDomain = {};
  for (const s of snaps) {
    (byDomain[s.domain_name] = byDomain[s.domain_name] || []).push(s.avg_profit_per_trip);
  }
  const ranked = Object.entries(byDomain)
    .map(([d, ps]) => [d, ps.reduce((a, b) => a + b, 0) / ps.length])
    .sort((a, b) => b[1] - a[1]);
  const [winner, winnerProfit] = ranked[0];
  return (
    <Card title={title} status="ok">
      <p className="finding-headline">
        Best domain: <span className="mono">{winner}</span> at $
        {winnerProfit.toFixed(2)} avg profit per trip.
      </p>
      <table className="kv">
        <tbody>
          {ranked.map(([d, p]) => (
            <tr key={d}>
              <td className="muted mono">{d}</td>
              <td className={`mono ${p >= 0 ? 'numpos' : 'numneg'}`}>${p.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function ScaleCard({ call }) {
  const title = 'Best scale model';
  if (call.loading) return <CardLoading title={title} />;
  if (call.error)   return <CardError title={title} error={call.error} />;
  const snaps = call.data?.latest_snapshots || [];
  if (!snaps.length) return <CardEmpty title={title}
    command={'python run_transforms.py --all-runs --all-scale-models'} />;
  const byScale = {};
  for (const s of snaps) {
    (byScale[s.scale_model_name] = byScale[s.scale_model_name] || []).push(s.avg_effective_profit);
  }
  const ranked = Object.entries(byScale)
    .map(([m, ps]) => [m, ps.reduce((a, b) => a + b, 0) / ps.length])
    .sort((a, b) => b[1] - a[1]);
  const [winner, winnerProfit] = ranked[0];
  return (
    <Card title={title} status="ok">
      <p className="finding-headline">
        Best scale: <span className="mono">{winner}</span> at $
        {winnerProfit.toFixed(2)} avg effective profit per trip.
      </p>
      <table className="kv">
        <tbody>
          {ranked.map(([m, p]) => (
            <tr key={m}>
              <td className="muted mono">{m}</td>
              <td className={`mono ${p >= 0 ? 'numpos' : 'numneg'}`}>${p.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function BestCombinationCard({ call }) {
  const title = 'Best (domain × scale) combination';
  if (call.loading) return <CardLoading title={title} />;
  if (call.error)   return <CardError title={title} error={call.error} />;
  const best  = call.data?.best_cell;
  const worst = call.data?.worst_cell;
  if (!best) return <CardEmpty title={title}
    command={'python run_transforms.py --all-runs --all-delivery-domains --all-scale-models'} />;
  return (
    <Card title={title} status={best.avg_effective_profit > 0 ? 'ok' : 'warn'}>
      <p className="finding-headline">
        Best: <span className="mono">{best.scenario_name}</span> /
        {' '}<span className="mono">{best.domain_name}</span> /
        {' '}<span className="mono">{best.scale_model_name}</span> at $
        {best.avg_effective_profit.toFixed(2)} avg effective profit.
      </p>
      {worst && worst !== best && (
        <p className="muted">
          Worst: <span className="mono">{worst.scenario_name}</span> /
          {' '}<span className="mono">{worst.domain_name}</span> /
          {' '}<span className="mono">{worst.scale_model_name}</span> at $
          {worst.avg_effective_profit.toFixed(2)}.
        </p>
      )}
    </Card>
  );
}

function ValidationCard({ call }) {
  const title = 'Validation status';
  if (call.loading) return <CardLoading title={title} />;
  if (call.error)   return <CardError title={title} error={call.error} />;
  const v = call.data;
  if (!v) return <CardEmpty title={title} command={'python run_validation.py'} />;
  const errs  = v.failed_by_severity?.ERROR ?? 0;
  const warns = v.failed_by_severity?.WARN  ?? 0;
  const status = errs ? 'err' : warns ? 'warn' : 'ok';
  return (
    <Card title={title} status={status}>
      <p className="finding-headline">
        {errs
          ? `${errs} ERROR rule${errs === 1 ? '' : 's'} failing — investigate before trusting any number above.`
          : warns
            ? `Clean of ERROR; ${warns} WARN${warns === 1 ? '' : 's'} present.`
            : 'All validation rules pass.'}
      </p>
      <table className="kv">
        <tbody>
          {Object.entries(v.counts_by_severity || {}).map(([sev, n]) => (
            <tr key={sev}>
              <td className="muted">{sev}</td>
              <td className="mono">{n}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
