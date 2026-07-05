"""
GoalOS environment variable definitions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvironmentVariable:
    """Represents a supported environment variable."""

    name: str
    default: str
    description: str


ENVIRONMENT_VARIABLES = (
    EnvironmentVariable(
        name="GOALOS_ENV",
        default="production",
        description="Application environment.",
    ),
    EnvironmentVariable(
        name="GOALOS_HOST",
        default="0.0.0.0",
        description="Host interface.",
    ),
    EnvironmentVariable(
        name="GOALOS_PORT",
        default="8000",
        description="Application port.",
    ),
    EnvironmentVariable(
        name="GOALOS_DATABASE_URL",
        default="postgresql+psycopg://goalos:goalos@localhost:5432/goalos",
        description="PostgreSQL connection string.",
    ),
    EnvironmentVariable(
        name="GOALOS_LOG_LEVEL",
        default="INFO",
        description="Logging level.",
    ),
)
