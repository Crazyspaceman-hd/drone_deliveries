"""FastAPI app entry point.

Run locally with::

    uvicorn api.main:app --reload

The dev frontend (``frontend/``) talks to this on
``http://localhost:8000`` via a Vite proxy at ``/api``.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import (
    analytics, business_intelligence, charts, experiments, runs, scenarios, validation,
)


app = FastAPI(
    title="Drone deliveries — analytical workbench",
    description=(
        "Thin pass-through API over the existing core modules. "
        "Endpoints are 1:1 with the analytical functions in `core/*` "
        "and the SQL files under `analytics/`."
    ),
    version="0.1.0",
)

# Local-only dev: allow the Vite dev server (default port 5173) to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


app.include_router(runs.router)
app.include_router(scenarios.router)
app.include_router(validation.router)
app.include_router(charts.router)
app.include_router(business_intelligence.router)
app.include_router(analytics.router)
app.include_router(experiments.router)
