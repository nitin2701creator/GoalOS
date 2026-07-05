"""
GoalOS application lifespan management.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.logging import configure_logging

logger = logging.getLogger("goalos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown events.
    """
    configure_logging()
    logger.info("GoalOS starting up.")
    try:
        yield
    finally:
        logger.info("GoalOS shutting down.")
