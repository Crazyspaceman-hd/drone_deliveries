import React from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api.js';
import { useApi } from './useApi.js';

/**
 * Project landing page.  The reviewer reads this first.  Goal: explain
 * what the project does, what conclusion it reaches, and how to navigate.
 * Deterministic, no LLM-generated prose.
 */
export function Overview() {
  const runsCall = useApi(api.runs);
  const expCall  = useApi(api.experiments);

  const runs        = runsCall.data?.runs || [];
  const experiments = expCall.data?.experiments || [];

  return (
    <div>
      <section className="panel">
        <h2 className="section-title">What this project explores</h2>
        <p>
          A synthetic data-engineering pipeline that asks one comparative
          question: <em>could drone delivery replace truck delivery, and
          under what assumptions does it stop looking attractive?</em>
        </p>
        <p>
          The simulator emits operational events at the trip / leg / telemetry
          level into SQLite.  Rerunnable transforms layer economic, delivery-
          domain and fleet-scale overlays on top of those events.  Every
          analytical answer is reproducible from one seed and one set of
          knobs.
        </p>
        <p className="muted">
          Synthetic and comparative — not predictive.  Numbers are useful
          for ranking scenarios against each other, not for forecasting
          real-world unit economics.
        </p>
      </section>

      <section className="panel start-here">
        <strong>Start here →{' '}</strong>
        <Link to="/finding">Main finding</Link>
        <span className="muted">
          {' '}— the headline numbers.  Then dig into{' '}
          <Link to="/domain-scale">Domain &amp; Scale</Link>{' '}
          to see how the conclusion shifts under different assumptions.
        </span>
      </section>

      <section>
        <h2 className="section-title">Current thesis</h2>
        <div className="finding-card">
          <p className="finding-headline">
            Drone delivery looks weak as broad truck replacement under
            baseline cost assumptions, but becomes more useful as a hybrid
            augmentation layer for low-payload, latency-sensitive deliveries
            in dense urban scale regimes.
          </p>
          <p className="muted">
            Every claim above is a structured query against the snapshot
            tables, visible on the Main Finding and Domain &amp; Scale
            pages.
          </p>
        </div>
      </section>

      <section>
        <h2 className="section-title">Architecture</h2>
        <div className="overview-cards">
          <div className="overview-card">
            <h3>Operational simulation</h3>
            <p className="muted">
              Event-driven simulator emits trips, telemetry pings, maintenance,
              emergencies, and obstacle warnings into <span className="mono">delivery_events</span>.
              Deterministic given (seed, scenario, n_trips).
            </p>
          </div>
          <div className="overview-card">
            <h3>Transform pipeline</h3>
            <p className="muted">
              Auto-discovered transforms (<span className="mono">economics</span>,
              {' '}<span className="mono">scale</span>,
              {' '}<span className="mono">telemetry</span>) read from the source layer
              and write to derived snapshot tables.  Every run is logged in
              {' '}<span className="mono">transformation_runs</span>.
            </p>
          </div>
          <div className="overview-card">
            <h3>Domain overlays</h3>
            <p className="muted">
              The same event stream is reinterpreted under four delivery
              domains (food / medical / retail / urgent documents).  Only
              demand-side numbers move; physics stays fixed.
            </p>
          </div>
          <div className="overview-card">
            <h3>Scale overlays</h3>
            <p className="muted">
              Four fleet-scale models amortise overhead across trip volume.
              The cross-section of (domain × scale) is the most reviewer-
              relevant analytical surface.
            </p>
          </div>
          <div className="overview-card">
            <h3>Validation &amp; lineage</h3>
            <p className="muted">
              Rule-based validator runs across the snapshot tables;
              {' '}<span className="mono">transformation_runs</span> carries
              git commit + parameter JSON per row so any analytical claim
              traces back to a source run.
            </p>
          </div>
        </div>
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
        <summary>Reproduce this analysis</summary>
        <pre className="mono">
{`python run_scenarios.py --scenarios urban_dense suburban_standard rural_extended --trips 100 --seed 42

python run_transforms.py --all-runs
python run_transforms.py --all-runs --all-delivery-domains
python run_transforms.py --all-runs --all-scale-models

python run_validation.py
python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts

uvicorn api.main:app --reload
cd frontend && npm install && npm run dev`}
        </pre>
      </details>
    </div>
  );
}
