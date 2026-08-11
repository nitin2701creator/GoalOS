"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseProvider(ABC):
    """Provider abstraction for pluggable language model backends."""

    @abstractmethod
    def request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        raise NotImplementedError


def provider_configured(provider: BaseProvider | None) -> bool:
    """Return whether the provider holds real credentials for generation.

    The FreeLLM placeholder reports healthy even without keys, so this
    checks the actual credential rather than the health flag — an
    unconfigured provider must never fabricate output.
    """
    if provider is None:
        return False
    config = getattr(provider, "_config", None)
    if config is not None:
        return bool(getattr(config, "api_key", None))
    return bool(getattr(provider, "api_key", None))
