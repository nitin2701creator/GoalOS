"""GoalOS Integrations Manager — main FastAPI application.

A secure, centralized dashboard for managing credentials for all GoalOS integrations.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from integrations_manager.app.config import settings
from integrations_manager.app.encryption import CredentialEncryption
from integrations_manager.app.models import Base, Integration, create_db_engine, init_db, get_session_factory
from integrations_manager.app.providers import PROVIDER_REGISTRY

# ── Lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and seed integrations on startup."""
    # Create engine & session
    engine = create_db_engine(settings.DATABASE_URL)
    init_db(engine)
    SessionLocal = get_session_factory(engine)
    db = SessionLocal()

    # Store on app state
    app.state.db = db
    app.state.engine = engine
    app.state.encryption = CredentialEncryption()

    # Seed default integrations
    _seed_integrations(db)

    yield

    db.close()


def _seed_integrations(db):
    """Create default integration records for all registered providers."""
    for slug, provider_cls in PROVIDER_REGISTRY.items():
        existing = db.query(Integration).filter(Integration.slug == slug).first()
        if existing:
            continue
        info = provider_cls().info()
        db.add(Integration(
            slug=info.slug,
            name=info.name,
            description=info.description,
            icon=info.icon,
            auth_type=info.auth_type,
            is_enabled=True,
        ))
    db.commit()


# ── App ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ── Routers ─────────────────────────────────────────────────────────────

from integrations_manager.app.routers.admin import router as admin_router
from integrations_manager.app.routers.integrations import router as integrations_router
from integrations_manager.app.routers.oauth import router as oauth_router

app.include_router(admin_router)
app.include_router(integrations_router)
app.include_router(oauth_router)


# ── Static files (frontend) ────────────────────────────────────────────

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


# ── Error handlers ──────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler — never expose internals."""
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
