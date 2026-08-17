import React from 'react';
import { api, chartUrl } from '../api.js';
import { useApi } from './useApi.js';

/**
 * Chart artifact browser.  Charts are a supporting layer — the primary
 * analytical UX is on the Main Finding and Domain & Scale pages.  The
 * gallery surfaces a small "Featured" row at the top with the
 * portfolio-headline charts, then groups everything else by category.
 */

// The three charts that carry the project's primary signal.  Featured
// rendering takes precedence over the category scheme below — files in
// FEATURED are pulled out of category buckets so they don't appear twice.
const FEATURED = [
  'viability_by_capacity_and_domain.png',
  'capacity_coupled_profit_by_volume.png',
  'validation_results.png',
];

// Category mapping by filename substring.  First match wins.
const CATEGORIES = [
  { key: 'operational', label: 'Operational',
    match: ['operational_profile', 'scenario_summary'] },
  { key: 'economics',   label: 'Economics',
    match: ['profitability', 'run_comparison', 'cost_per_delivery'] },
  { key: 'hybrid',      label: 'Hybrid logistics',
    match: ['hybrid_activation', 'delivery_latency_by_mode',
            'queue_pressure', 'displacement'] },
  { key: 'domain_scale', label: 'Domain & scale',
    match: ['revenue_by_delivery_domain', 'scale',
            'effective_profit_by_delivery_volume',
            'amortized_overhead_by_delivery_volume',
            'required_drones', 'domain_response_components'] },
  { key: 'telemetry',   label: 'Telemetry',
    match: ['battery_temperature', 'signal_quality', 'telemetry'] },
  { key: 'validation',  label: 'Validation & calibration',
    match: ['validation', 'calibration', 'feasibility'] },
  { key: 'other',       label: 'Other artifacts',
    match: [] },
];

// One-liner captions for the well-known charts.
const CAPTIONS = {
  'viability_by_capacity_and_domain.png':
    'The answer card: green/yellow/red verdict per (capacity × domain) cell.',
  'capacity_coupled_profit_by_volume.png':
    'Small multiples — effective profit by volume per capacity model. ' +
    'Solid = within addressable demand, dashed = extrapolation.',
  'validation_results.png':
    'Rule pass/fail counts by severity.',
  'scenario_operational_profile.png':
    'Trip distance, telemetry density and event mix per scenario.',
  'scenario_profitability.png':
    'Average profit per trip ranked by scenario.',
  'run_comparison_profit.png':
    'Per-run total profit comparison (multi-run DBs only).',
  'hybrid_activation_breakdown.png':
    'Share of orders flagged drone / hybrid / truck by scenario.',
  'delivery_latency_by_mode.png':
    'Average latency by fulfillment mode.',
  'queue_pressure_vs_drone_activation.png':
    'Drone activation rate vs simulated queue pressure.',
  'revenue_by_delivery_domain.png':
    'Average revenue per trip per delivery domain.',
  'cost_per_delivery_by_scale.png':
    'Effective cost per delivery under each scale model.',
  'effective_profit_by_delivery_volume.png':
    '[Phase 27 legacy] Smooth 1/x amortization — kept as the visible "before".',
  'amortized_overhead_by_delivery_volume.png':
    '[Phase 27 legacy] Overhead per delivery under the fixed-overhead formula.',
  'required_drones_by_delivery_volume.png':
    'Required fleet staircase — the driver of capacity overhead.',
  'domain_response_components_by_volume.png':
    'Phase 29 decomposition: efficiency credit + value decay + net response, per domain.',
  'battery_temperature_by_scenario.png':
    'Distribution of telemetry battery temperatures per scenario.',
  'signal_quality_distribution.png':
    'Signal-quality distribution across telemetry pings.',
  'scenario_calibration_drift.png':
    'Observed minus configured event rates per scenario.',
  'scenario_feasibility.png':
    'Composite feasibility score per scenario.',
};

function categorize(filename) {
  for (const c of CATEGORIES) {
    if (c.match.some((m) => filename.includes(m))) return c.key;
  }
  return 'other';
}

export function ChartGallery() {
  const { data, error, loading } = useApi(api.charts);
  if (loading) return <div className="panel muted">Loading chart list…</div>;
  if (error)   return <div className="panel error">{error}</div>;
  const charts = data?.charts || [];
  if (!charts.length) return (
    <div className="empty-state">
      No PNGs in <span className="mono">{data?.charts_dir}</span> yet.
      Run:
      <pre className="mono">python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts</pre>
    </div>
  );
  // Pull the Featured set out first so it can't double-up in category buckets.
  const present  = new Set(charts);
  const featured = FEATURED.filter((name) => present.has(name));
  const featuredSet = new Set(featured);

  const grouped = {};
  for (const name of charts) {
    if (featuredSet.has(name)) continue;  // already in Featured
    const k = categorize(name);
    (grouped[k] = grouped[k] || []).push(name);
  }

  function Figure({ name }) {
    return (
      <figure>
        <img src={chartUrl(name)} alt={name} loading="lazy" />
        <figcaption>
          <div className="mono">{name}</div>
          {CAPTIONS[name] && <div className="muted">{CAPTIONS[name]}</div>}
        </figcaption>
      </figure>
    );
  }

  return (
    <div>
      <p className="muted section-lead">
        Pre-rendered chart artifacts produced by{' '}
        <span className="mono">run_visualizations.py</span>.  The Featured
        row carries the project's primary signal; the categorised
        sections below are supporting and historical detail.
      </p>

      {featured.length > 0 && (
        <section>
          <h2 className="section-title">Featured</h2>
          <div className="chart-grid">
            {featured.map((name) => <Figure key={name} name={name} />)}
          </div>
        </section>
      )}

      {CATEGORIES.map((c) => {
        const items = grouped[c.key] || [];
        if (!items.length) return null;
        return (
          <section key={c.key}>
            <h2 className="section-title">{c.label}</h2>
            <div className="chart-grid">
              {items.map((name) => <Figure key={name} name={name} />)}
            </div>
          </section>
        );
      })}
    </div>
  );
}
