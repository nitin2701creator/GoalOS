"""Configuration for GoalOS language-model communication."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Runtime settings used by the shared language-model client.

    Environment variable names use the ``FREELLM_`` prefix. Legacy GoalOS
    variable names are also supported to keep existing local configuration
    working during the infrastructure migration.
    """

    base_url: str = "https://api.freellm.example.com"
    api_key: str | None = None
    timeout: float = 30.0
    default_model: str = "free-llm-small"
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Build configuration from environment variables.

        Raises:
            ValueError: If a numeric setting is invalid or negative.
        """

        return cls(
            base_url=_environment_value(
                "FREELLM_BASE_URL",
                "FREELLMAPI_BASE_URL",
                default=cls.base_url,
            ),
            api_key=_environment_value(
                "FREELLM_API_KEY", "FREELLMAPI_API_KEY", default=None
            ),
            timeout=_positive_float(
                _environment_value("FREELLM_TIMEOUT", "LLM_TIMEOUT", default="30"),
                "timeout",
            ),
            default_model=_environment_value(
                "FREELLM_DEFAULT_MODEL", "DEFAULT_MODEL", default=cls.default_model
            ),
            max_retries=_non_negative_int(
                _environment_value("FREELLM_MAX_RETRIES", "LLM_MAX_RETRIES", default="3"),
                "max_retries",
            ),
        )


def _environment_value(*names: str, default: str | None) -> str | None:
    """Return the first configured environment value from ``names``."""

    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return default


def _positive_float(value: str | None, setting: str) -> float:
    """Validate a positive numeric environment setting."""

    try:
        parsed_value = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{setting} must be a positive number") from error
    if parsed_value <= 0:
        raise ValueError(f"{setting} must be a positive number")
    return parsed_value


def _non_negative_int(value: str | None, setting: str) -> int:
    """Validate a non-negative integer environment setting."""

    try:
        parsed_value = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{setting} must be a non-negative integer") from error
    if parsed_value < 0:
        raise ValueError(f"{setting} must be a non-negative integer")
    return parsed_value
