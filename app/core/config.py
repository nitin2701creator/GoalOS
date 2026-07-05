"""
GoalOS configuration helpers.
"""

from __future__ import annotations

from app.core.settings import settings


class Config:
    """Application configuration wrapper."""

    APP_NAME = settings.app_name
    ENVIRONMENT = settings.environment
    HOST = settings.host
    PORT = settings.port
    DATABASE_URL = settings.database_url


config = Config()
