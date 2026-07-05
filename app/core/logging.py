"""
GoalOS logging configuration.
"""

from __future__ import annotations

import logging
from logging.config import dictConfig

from app.core.config import config


def configure_logging() -> None:
    """Configure application logging."""
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {
                "handlers": ["console"],
                "level": "INFO",
            },
        }
    )

    logging.getLogger("goalos").info(
        "Logging initialized for %s (%s)",
        config.APP_NAME,
        config.ENVIRONMENT,
    )
