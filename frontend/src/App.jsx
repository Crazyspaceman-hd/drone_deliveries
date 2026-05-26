import React from 'react';
import {
  BrowserRouter, NavLink, Route, Routes, Navigate,
} from 'react-router-dom';

import { Overview }              from './components/Overview.jsx';
import { MainFinding }            from './components/MainFinding.jsx';
import { RunExplorer }            from './components/RunExplorer.jsx';
import { ExperimentsList,
         ExperimentDetail }       from './components/Experiments.jsx';
import { DomainScaleAnalysis }    from './components/DomainScaleAnalysis.jsx';
import { HybridOperations }       from './components/HybridOperations.jsx';
import { OperationalTelemetry }   from './components/OperationalTelemetry.jsx';
import { ValidationPanel }        from './components/ValidationPanel.jsx';
import { ChartGallery }           from './components/ChartGallery.jsx';
// ScenarioComparison + DeliveryImpactView reachable via direct routes
// (kept available for reviewers who want them; not on primary nav).
import { ScenarioComparison }     from './components/ScenarioComparison.jsx';
import { DeliveryImpactView }     from './components/DeliveryImpactView.jsx';

/**
 * Navigation order is deliberately narrative:
 *   Overview → why
 *   Main finding → what was found
 *   Runs → what evidence
 *   Experiments → systematic sweeps
 *   Domain & Scale → how the answer shifts under assumptions
 *   Hybrid → the augmentation alternative
 *   Telemetry → operational source layer detail
 *   Validation → trust in the numbers
 *   Charts → supporting artifacts
 */
const NAV = [
  { to: '/',              label: 'Overview'         },
  { to: '/finding',       label: 'Main finding'     },
  { to: '/runs',          label: 'Runs'             },
  { to: '/experiments',   label: 'Experiments'      },
  { to: '/domain-scale',  label: 'Domain & Scale'   },
  { to: '/hybrid',        label: 'Hybrid'           },
  { to: '/telemetry',     label: 'Telemetry'        },
  { to: '/validation',    label: 'Validation'       },
  { to: '/charts',        label: 'Charts'           },
];

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <header className="app-header">
          <h1>Drone deliveries — analytical workbench</h1>
          <p className="lede">
            Read-only view onto a synthetic data-engineering pipeline.
            Comparative, deterministic, not predictive.
          </p>
        </header>

        <nav className="primary-nav">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>

        <main className="app-main">
          <Routes>
            <Route path="/"              element={<Overview />} />
            <Route path="/finding"       element={<MainFinding />} />
            <Route path="/runs"          element={<RunExplorer />} />
            <Route path="/experiments"   element={<ExperimentsList />} />
            <Route path="/experiments/:id" element={<ExperimentDetail />} />
            <Route path="/domain-scale"  element={<DomainScaleAnalysis />} />
            <Route path="/hybrid"        element={<HybridOperations />} />
            <Route path="/telemetry"     element={<OperationalTelemetry />} />
            <Route path="/validation"    element={<ValidationPanel />} />
            <Route path="/charts"        element={<ChartGallery />} />
            {/* Legacy/secondary views — reachable by direct URL */}
            <Route path="/scenarios"     element={<ScenarioComparison />} />
            <Route path="/impact"        element={<DeliveryImpactView />} />
            <Route path="*"              element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        <footer className="app-footer">
          <span className="muted">
            Synthetic data only.  See README §Workbench walkthrough for
            commands.
          </span>
        </footer>
      </div>
    </BrowserRouter>
  );
}
