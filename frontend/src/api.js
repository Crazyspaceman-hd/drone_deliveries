// Tiny fetch wrapper.  Every request hits /api/* which Vite proxies to
// http://localhost:8000 in dev (see vite.config.js).

async function get(path) {
  const res = await fetch(`/api${path}`);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`GET /api${path} → ${res.status} ${text}`);
  }
  return res.json();
}

export const api = {
  health:             () => get('/health'),
  runs:               () => get('/runs'),
  run:                (id) => get(`/runs/${encodeURIComponent(id)}`),
  runTransforms:      (id) => get(`/runs/${encodeURIComponent(id)}/transforms`),
  scenarios:          () => get('/scenarios'),
  scenariosSummary:   () => get('/scenarios/summary'),
  validation:         () => get('/validation'),
  charts:             () => get('/charts'),
  bi:                 () => get('/business-intelligence'),
  displacement:       (truckCost) =>
    get(`/analytics/delivery-displacement${truckCost
      ? `?truck_cost_per_delivery=${truckCost}` : ''}`),
  hybridSummary:      () => get('/analytics/hybrid-summary'),
  latency:            () => get('/analytics/latency'),
  activationReasons:  () => get('/analytics/activation-reasons'),
  telemetrySummary:   () => get('/analytics/telemetry-summary'),
  telemetryHealth:    () => get('/analytics/telemetry-health'),
  deliveryDomains:    () => get('/analytics/delivery-domains'),
  scaleModels:        () => get('/analytics/scale-models'),
  domainScaleMatrix:  () => get('/analytics/domain-scale-matrix'),
  volumeSensitivity:  (capacityModel) =>
    get(`/analytics/volume-sensitivity${capacityModel
      ? `?capacity_model=${encodeURIComponent(capacityModel)}` : ''}`),
  viabilitySummary:   () => get('/analytics/viability-summary'),
  experiments:        () => get('/experiments'),
  experiment:         (id) => get(`/experiments/${encodeURIComponent(id)}`),
};

// PNG endpoint is consumed directly via <img src="/api/charts/<file>">.
export const chartUrl = (name) => `/api/charts/${encodeURIComponent(name)}`;
