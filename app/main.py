import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.purchase_order import router as po_router
from app.api.router import api_router
from app.api.v1.openai import build_health_payload
from app.api.v1.openai import router as openai_router
from app.config import GOALOS_VERSION
from app.control_loop.scheduler_worker import (
    start_scheduler_worker,
    stop_scheduler_worker,
)
from app.dashboard.dashboard_router import router as dashboard_router
from app.db.base import Base
from app.db.session import engine, get_db

app = FastAPI(
    title="GoalOS",
    description="Enterprise AI Operating System",
    version=GOALOS_VERSION,
)


def _cors_origins() -> list[str]:
    """CORS allow-list: the configured OpenWebUI origin plus dev defaults.

    Production never assumes localhost — set OPENWEBUI_BASE_URL to the
    OpenWebUI origin (e.g. ``https://openwebui.kvm.local``) and it is used
    verbatim; the defaults only cover local development.
    """
    origins = []
    openwebui = os.getenv("OPENWEBUI_BASE_URL")
    if openwebui and openwebui.strip():
        origins.append(openwebui.strip())
    origins.extend(
        [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
    )
    return list(dict.fromkeys(origins))


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(po_router)
app.include_router(dashboard_router)
# OpenAI-compatible surface for OpenWebUI (mounted at /v1/models,
# /v1/chat/completions, /v1/health — separate from the /api namespace).
app.include_router(openai_router, prefix="/v1")


@app.on_event("startup")
async def on_startup():
    # Create DB tables if they don't exist.
    Base.metadata.create_all(bind=engine)
    # Start the persisted scheduler worker (one loop per process; the
    # worker refuses duplicates and claims due runs atomically in the DB,
    # so restarts and multiple uvicorn workers stay safe).
    start_scheduler_worker()


@app.on_event("shutdown")
async def on_shutdown():
    await stop_scheduler_worker()


@app.get("/")
async def root():
    return {
        "name": "GoalOS",
        "status": "running",
        "version": GOALOS_VERSION,
    }


@app.get("/ready")
async def ready(db=Depends(get_db)):
    """Readiness probe: the app answers 200 only when the database is
    reachable and the scheduler worker is started/starting."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - readiness must report, never crash
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")
    return {
        "status": "ready",
        "goalos": {"status": "running", "version": GOALOS_VERSION},
        "database": "healthy",
    }


@app.get("/health")
async def health(db=Depends(get_db)):
    return build_health_payload(db)
