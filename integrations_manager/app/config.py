"""Configuration for the GoalOS Integrations Manager.

All secrets are loaded from environment variables only.
Never hard-code credentials.
"""
from __future__ import annotations

import os


class Settings:
    """Application settings loaded from environment variables."""

    # ── App ──────────────────────────────────────────────────────────────
    APP_NAME: str = "GoalOS Integrations Manager"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("IM_DEBUG", "false").lower() in ("1", "true", "yes")

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv(
        "IM_DATABASE_URL",
        "sqlite:///./integrations_manager.db",
    )

    # ── Master encryption key for credential storage ─────────────────────
    # MUST be set in production. 32-byte hex string (64 hex chars).
    ENCRYPTION_KEY: str = os.getenv("IM_ENCRYPTION_KEY", "")

    # ── Admin credentials ────────────────────────────────────────────────
    ADMIN_USERNAME: str = os.getenv("IM_ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("IM_ADMIN_PASSWORD", "changeme")

    # ── JWT auth ─────────────────────────────────────────────────────────
    JWT_SECRET: str = os.getenv("IM_JWT_SECRET", os.urandom(32).hex())
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = int(os.getenv("IM_JWT_EXPIRY_MINUTES", "60"))

    # ── CORS / origins ──────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv("IM_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
        if o.strip()
    ]

    # ── Rate limiting ────────────────────────────────────────────────────
    RATE_LIMIT_LOGIN: str = os.getenv("IM_RATE_LIMIT_LOGIN", "5/minute")
    RATE_LIMIT_API: str = os.getenv("IM_RATE_LIMIT_API", "60/minute")

    # ── OAuth redirect base ──────────────────────────────────────────────
    OAUTH_REDIRECT_BASE: str = os.getenv(
        "IM_OAUTH_REDIRECT_BASE",
        "http://localhost:8001",
    )

    # ── Google OAuth ─────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

    # ── Meta/Facebook OAuth ──────────────────────────────────────────────
    META_APP_ID: str = os.getenv("META_APP_ID", "")
    META_APP_SECRET: str = os.getenv("META_APP_SECRET", "")

    # ── LinkedIn OAuth ───────────────────────────────────────────────────
    LINKEDIN_CLIENT_ID: str = os.getenv("LINKEDIN_CLIENT_ID", "")
    LINKEDIN_CLIENT_SECRET: str = os.getenv("LINKEDIN_CLIENT_SECRET", "")

    # ── Reddit OAuth ─────────────────────────────────────────────────────
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_REDIRECT_URI: str = os.getenv(
        "REDDIT_REDIRECT_URI",
        "http://localhost:8001/api/oauth/reddit/callback",
    )


settings = Settings()
