import React from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api.js';
import { useApi } from './useApi.js';
import { ViabilityGrid } from './ViabilityGrid.jsx';

/**
 * Guided landing page.  Conclusion-first.
 *
 * Order is deliberate:
 *   1. Thesis (one paragraph)
 *   2. Viability grid (the answer)
 *   3. How to read it (two sentences)
 *   4. Where to go next (three explicit links)
 *   5. Architecture (collapsible, demoted from primary)
 *   6. Reproduce (collapsible, kept for transparency)
 */
export function Overview() {
  const runsCall = useApi(api.runs);
  const expCall  = useApi(api.experiments);

  const runs        = runsCall.data?.runs || [];
  const experiments = expCall.data?.experiments || [];

  return (
    <div>
      <section className="panel">
        <h2 className="section-title">Thesis</h2>
        <p>
          Drone delivery economics depend on three coupled assumptions:
          how productive each drone is, how much demand the domain can
          address, and how overhead amortises across the volume served.
          This project models all three as <em>synthetic comparative</em>
          knobs and asks a single question per cell: <em>at what delivery
          volume does the model find break-even, and does that volume sit
          inside the domain's addressable demand?</em>
        </p>
        <p className="muted">
          Synthetic and comparative — not predictive.  The numbers below
          rank scenarios against each other under transparent assumptions,
          not against real-world unit economics.
        </p>
      </section>

      <ViabilityGrid />

      <section className="panel">
        <h2 className="section-title">How to read it</h2>
        <p>
          <strong>Green</strong> cells: the model finds break-even at the
          listed delivery volume, and that volume sits inside the
          domain's addressable demand. <strong>Yellow</strong> cells:
          break-even exists but only past the addressable ceiling — an
          extrapolation, not a conclusion. <strong>Red</strong> cells:
          no sweep point clears zero; capacity overhead dominates across
          the entire addressable range.
        </p>
      </section>

      <section className="panel start-here">
        <strong>Where to go next →{' '}</strong>
        <Link to="/finding">Main Finding</Link>
        <span className="muted"> for the deterministic numbers behind the grid · </span>
        <Link to="/domain-scale">Domain &amp; Scale</Link>
        <span className="muted"> for the line-chart small multiples and the volume sweep · </span>
        <Link to="/runs">Runs</Link>
        <span className="muted"> for raw simulation lineage.</span>
      </section>

      <section>
        <h2 className="section-title">Where the data is</h2>
        <div className="metric-grid">
          <div className="metric">
            <div className="label">Simulation runs</div>
            <div className="value">{runsCall.loading ? '…' : runs.length}</div>
          </div>
          <div className="metric">
            <div className="label">Experiments</div>
            <div className="value">{expCall.loading ? '…' : experiments.length}</div>
          </div>
        </div>
        {!runsCall.loading && !runs.length && (
          <div className="empty-state">
            No simulation runs found.  Populate with:
            <pre className="mono">python run_scenarios.py --scenarios urban_dense suburban_standard rural_extended --trips 100 --seed 42</pre>
          </div>
        )}
      </section>

      <details className="reproduce">
        <summary>Architecture summary</summary>
        <div className="overview-cards" style={{ marginTop: 12 }}>
          <div className="overview-card">
            <h3>Operational simulation</h3>
            <p className="muted">
              Event-driven simulator emits trips, telemetry, maintenance,
              emergencies into <span className="mono">delivery_events</span>.
              Deterministic given (seed, scenario, n_trips).
            </p>
          </div>
          <div className="overview-card">
            <h3>Transform pipeline</h3>
            <p className="muted">
              Auto-discovered transforms (economics, scale, hybrid,
              telemetry) read the source layer and write to derived
              snapshot tables.  Every run is logged.
            </p>
          </div>
          <div className="overview-card">
            <h3>Domain overlays</h3>
            <p className="muted">
              The same event stream is reinterpreted under four delivery
              domains.  Only demand-side numbers move; physics stays fixed.
            </p>
          </div>
          <div className="overview-card">
            <h3>Capacity coupling</h3>
            <p className="muted">
              Required fleet, operators, chargers, and maintenance are
              <em> derived</em> from delivery volume, not asserted.
              Daily overhead is the sum of those derived counts × per-resource cost.
            </p>
          </div>
          <div className="overview-card">
            <h3>Validation &amp; lineage</h3>
            <p className="muted">
              Rule-based validator runs across snapshot tables;
              <span className="mono"> transformation_runs</span> carries
              git commit + parameter JSON per row so any analytical
              claim traces back to a source run.
            </p>
          </div>
        </div>
      </details>

      <details className="reproduce">
        <summary>Reproduce this analysis</summary>
        <pre className="mono">
{`# Seed the DB:
python run_scenarios.py --scenarios urban_dense suburban_standard rural_extended --trips 100 --seed 42
python run_transforms.py --all-runs
python run_transforms.py --all-runs --all-delivery-domains
python run_transforms.py --all-runs --all-scale-models

# Render charts:
python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts

# Launch the workbench (single command, opens http://localhost:5173):
python workbench.py`}
        </pre>
      </details>
    </div>
  );
}
