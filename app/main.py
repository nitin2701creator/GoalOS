import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
from app.db.schema import ensure_schema
from app.db.session import SessionLocal, engine, get_db
from app.services.credential_service import CredentialService
from app.services.google_oauth_service import GoogleOAuthService
from app.services.integration_service import IntegrationService

logger = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging() -> None:
    """Configure root logging for deployment diagnosis.

    Level comes from ``GOALOS_LOG_LEVEL`` (default ``INFO``); invalid
    values fall back to INFO so a typo never breaks startup. Uvicorn's
    own loggers propagate through the same handler.
    """
    level = os.getenv("GOALOS_LOG_LEVEL", "INFO").strip().upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        level = "INFO"
    logging.basicConfig(level=level, format=_LOG_FORMAT)


configure_logging()

app = FastAPI(
    title="GoalOS",
    description="Enterprise AI Operating System",
    version=GOALOS_VERSION,
)


def _cors_origins() -> list[str]:
    """CORS allow-list: LibreChat, dev defaults, and configured origins.

    Production never assumes localhost — set GOALOS_CORS_ORIGINS to a
    comma-separated list of allowed origins, or use the default
    which covers LibreChat on port 3080 and common dev ports.
    """
    origins = []
    custom = os.getenv("GOALOS_CORS_ORIGINS")
    if custom and custom.strip():
        origins.extend(o.strip() for o in custom.split(",") if o.strip())
    origins.extend(
        [
            "http://localhost:3080",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
    )
    # Legacy env var for backward compatibility.
    openwebui = os.getenv("OPENWEBUI_BASE_URL")
    if openwebui and openwebui.strip():
        origins.append(openwebui.strip())
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
# OpenAI-compatible surface for LibreChat (mounted at /v1/models,
# /v1/chat/completions, /v1/health — separate from the /api namespace).
app.include_router(openai_router, prefix="/v1")

# --- Static file serving for the credentials dashboard ---
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/integrations", response_class=FileResponse)
async def integrations_dashboard():
    """Serve the integrations credentials dashboard."""
    index = _STATIC_DIR / "credentials" / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return FileResponse(str(index), media_type="text/html")


@app.on_event("startup")
async def on_startup():
    # Create DB tables if they don't exist.
    Base.metadata.create_all(bind=engine)
    # Apply idempotent schema additions to pre-existing databases
    # (create_all never adds columns to existing tables).
    ensure_schema(engine)
    # Persist the integration registry (name/type/enabled/capabilities/
    # config references) from the connector registry. Idempotent and
    # non-fatal: a registry sync failure must never block startup.
    try:
        with SessionLocal() as db:
            IntegrationService(db).sync()
    except Exception as exc:  # noqa: BLE001 - registry sync must not block startup
        logger.warning("integration registry sync failed at startup: %s", exc)
    # Hydrate a refresh token granted through the Google OAuth web flow
    # into the process environment so the Gmail / Calendar / Drive
    # connectors (which read configuration from env vars) stay configured
    # across restarts. Non-fatal: without a stored token the connectors
    # simply report Not Configured, exactly as before.
    try:
        GoogleOAuthService(SessionLocal()).load_into_environment()
    except Exception as exc:  # noqa: BLE001 - hydration must not block startup
        logger.warning("google oauth credential hydration failed at startup: %s", exc)
    # Hydrate all encrypted credentials into the process environment
    # so connectors pick them up on restart.
    try:
        CredentialService(SessionLocal()).hydrate_all()
    except Exception as exc:  # noqa: BLE001 - credential hydration must not block startup
        logger.warning("encrypted credential hydration failed at startup: %s", exc)
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
