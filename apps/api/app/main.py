from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    analytics,
    cohorts,
    entities,
    health,
    openalex,
    registry,
    reports,
    runs,
    slices,
    snapshot,
    sources,
    state,
    tables,
)


app = FastAPI(
    title="OpenAlex DSS API",
    version="0.3.0",
    description="Versioned API for the OpenAlex scientometric decision support workspace.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_v1 = APIRouter(prefix="/api/v1")
for router in (
    health.router,
    openalex.router,
    slices.router,
    state.router,
    sources.router,
    tables.router,
    entities.router,
    cohorts.router,
    analytics.router,
    snapshot.router,
    runs.router,
    registry.router,
    reports.router,
):
    api_v1.include_router(router)

app.include_router(api_v1)


@app.get("/", tags=["health"])
def root() -> dict[str, str]:
    return {
        "name": "OpenAlex DSS API",
        "version": app.version,
        "api": "/api/v1",
        "docs": "/docs",
    }


@app.get("/health", tags=["health"])
def root_health() -> dict[str, str]:
    return {"status": "ok", "api": "/api/v1"}
