"""RAHAT application entrypoint.

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from . import repository as repo
from . import seed as seeder
from . import telemetry
from .api import router
from .config import settings
from .services import forecast_service as fs


@asynccontextmanager
async def lifespan(app: FastAPI):
    stats = seeder.seed()
    repo.invalidate()
    # Train off the event loop: the booster is CPU-bound and the dashboard must
    # not block on it.
    fs.warm_in_background()
    telemetry.hub.start()
    app.state.seed = stats
    app.state.started_at = repo.now_iso()
    yield
    if telemetry.hub._task is not None:
        telemetry.hub._task.cancel()


app = FastAPI(
    title="RAHAT - Predictive Forward Supply Chain",
    version=settings.version,
    description=(
        "**SIH 2026 · PS `SIH26251` · Indian Army - Predictive Logistics & "
        "Forward Supply Chain.**\n\n"
        "Four pillars of the problem statement map to four endpoint groups:\n\n"
        "| PS pillar | Endpoints |\n"
        "|---|---|\n"
        "| AI/ML demand forecasting | `/api/v1/forecast`, `/api/v1/forecast/leaderboard` |\n"
        "| GIS-enabled logistics planning | `/api/v1/plan/*`, `/api/v1/theatre` |\n"
        "| IoT inventory tracking | `/api/v1/inventory`, `/api/v1/sensors` |\n"
        "| Integrated predictive logistics | `/api/v1/simulate`, `/api/v1/resilience/*` |\n\n"
        "No operational data was used: the theatre is a deterministic synthetic "
        "generator calibrated against open public sources. See `docs/`."
    ),
    lifespan=lifespan,
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return {
        "app": settings.app_name,
        "tagline": settings.app_tagline,
        "ps": settings.ps_number,
        "docs": "/docs",
        "api": "/api/v1",
        "health": "/api/v1/health",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse(url="/api/v1/health")


def _mount_frontend() -> None:
    """Serve a statically-exported frontend when present (air-gapped / Docker).

    In development Next.js runs on :3000 and proxies /api here, so this is a
    no-op unless RAHAT_STATIC_DIR points at a build output directory.
    """
    static_dir = os.environ.get("RAHAT_STATIC_DIR")
    if not static_dir or not os.path.isdir(static_dir):
        return
    from fastapi.staticfiles import StaticFiles

    app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")


_mount_frontend()
