"""Centralized GoalOS runtime configuration.

Every runtime setting GoalOS needs at deployment time lives here, read
from environment variables with safe defaults. Nothing is hard-coded into
services: credentials, providers, URLs, and scheduler tuning are all
configured through these settings (or the existing ``LLMConfig``).

Canonical environment variables:

- ``GOALOS_SCHEDULER_ENABLED`` — start the persisted scheduler worker
  loop with the application (``1``/``true``/``yes``, default ``1``).
- ``GOALOS_SCHEDULER_INTERVAL`` — poll interval in seconds for due runs
  (default ``30``).
- ``GOALOS_SCHEDULER_CLAIM_HORIZON`` — seconds a scheduled run is
  claimed by one worker so duplicate loops in other processes cannot
  double-execute it (default ``900``).
- ``GOALOS_DATABASE_URL`` — database URL (consumed by ``app.db.session``).
- ``GOALOS_REPOSITORY`` — repository root for development workers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: GoalOS version reported by the health/ready endpoints.
GOALOS_VERSION = "0.5.0"


def _env_bool(*names: str, default: bool) -> bool:
    """Return the first configured boolean environment value."""
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return default


def _env_number(
    *names: str,
    default: float,
    minimum: float,
    setting: str,
) -> float:
    """Return the first configured numeric environment value, validated."""
    for name in names:
        value = os.getenv(name)
        if value is None or not value.strip():
            continue
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ValueError(f"{setting} must be a number") from exc
        if parsed < minimum:
            raise ValueError(f"{setting} must be >= {minimum}")
        return parsed
    return default


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Runtime settings for the GoalOS scheduler/worker and deployment.

    Attributes:
        scheduler_enabled: Whether the persisted scheduler worker loop
            should run inside the application process.
        scheduler_interval: Poll interval (seconds) for due runs.
        scheduler_claim_horizon: Seconds a due run stays claimed so
            multiple workers cannot double-execute it.
    """

    scheduler_enabled: bool = True
    scheduler_interval: float = 30.0
    scheduler_claim_horizon: int = 900

    @classmethod
    def from_env(cls) -> RuntimeSettings:
        """Build settings from environment variables with safe defaults."""
        return cls(
            scheduler_enabled=_env_bool(
                "GOALOS_SCHEDULER_ENABLED",
                default=True,
            ),
            scheduler_interval=_env_number(
                "GOALOS_SCHEDULER_INTERVAL",
                default=30.0,
                minimum=1.0,
                setting="GOALOS_SCHEDULER_INTERVAL",
            ),
            scheduler_claim_horizon=int(
                _env_number(
                    "GOALOS_SCHEDULER_CLAIM_HORIZON",
                    default=900.0,
                    minimum=30.0,
                    setting="GOALOS_SCHEDULER_CLAIM_HORIZON",
                )
            ),
        )


#: Process-wide settings instance; services read from here unless a test
#: injects a dedicated instance.
settings = RuntimeSettings.from_env()
