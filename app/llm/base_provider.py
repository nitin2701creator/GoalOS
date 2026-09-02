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


# Placeholder base URL that indicates no real provider is configured.
_PLACEHOLDER_URL = "https://api.freellm.example.com"


def provider_configured(provider: BaseProvider | None) -> bool:
    """Return whether the provider is configured for real LLM generation.

    The FreeLLM placeholder reports healthy even without keys, so this
    checks the actual configuration rather than the health flag — an
    unconfigured provider must never fabricate output.

    For OpenAI-compatible providers, a base URL and model are sufficient
    (local providers like Ollama/vLLM don't require an API key). The
    placeholder ``https://api.freellm.example.com`` is never treated as
    a real configuration.
    """
    if provider is None:
        return False
    # OpenAI-compatible providers with a real base_url + model are
    # configured even without an api_key (local inference).
    config = getattr(provider, "_config", None)
    if config is not None:
        base_url = getattr(config, "base_url", None)
        model = getattr(config, "default_model", None)
        if base_url and model and base_url != _PLACEHOLDER_URL:
            return True
        return bool(getattr(config, "api_key", None))
    # FreeLLM placeholder: requires api_key to be meaningful.
    return bool(getattr(provider, "api_key", None))
