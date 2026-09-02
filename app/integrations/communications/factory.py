"""Communication provider factory for GoalOS.

Selects the active provider from COMMUNICATION_PROVIDER or
COMMUNICATION_PRIMARY_PROVIDER / COMMUNICATION_FALLBACK_PROVIDER
environment variables and instantiates the correct adapter.

Returns None when no provider is configured rather than crashing.
Supports primary + fallback provider chains.
"""

from __future__ import annotations

import logging
import os

from app.integrations.communications.base import (
    BaseCommunicationAdapter,
    CommunicationConfig,
)

logger = logging.getLogger(__name__)

#: Registry of known providers and their adapter classes.
# Avoid circular imports by lazily importing.
_PROVIDER_CLASSES: dict[str, str] = {
    "twilio": "app.integrations.communications.twilio_adapter.TwilioAdapter",
    "plivo": "app.integrations.communications.plivo_adapter.PlivoAdapter",
}


def _load_class(dotted_path: str) -> type[BaseCommunicationAdapter]:
    """Lazily import a provider adapter class."""
    module_path, _, class_name = dotted_path.rpartition(".")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_provider_class(name: str) -> type[BaseCommunicationAdapter] | None:
    """Return the adapter class for a provider name, or None if unknown."""
    dotted = _PROVIDER_CLASSES.get(name.strip().lower())
    if dotted is None:
        return None
    return _load_class(dotted)


def _build_provider(name: str) -> BaseCommunicationAdapter | None:
    """Instantiate a single provider by name, or None."""
    name = name.strip().lower()
    if not name:
        return None
    cls = get_provider_class(name)
    if cls is None:
        logger.warning("Unknown communication provider: %s", name)
        return None
    return cls()


def get_active_provider() -> BaseCommunicationAdapter | None:
    """Return the primary configured provider.

    Resolution order:
    1. COMMUNICATION_PROVIDER (legacy single-provider env var)
    2. COMMUNICATION_PRIMARY_PROVIDER (Sprint 2 primary/fallback)
    3. None if neither is set

    Note: this returns only the primary provider. Use
    get_provider_chain() to get the full primary → fallback chain.
    """
    # Legacy single-provider env
    provider_name = os.getenv("COMMUNICATION_PROVIDER", "").strip()
    if provider_name:
        return _build_provider(provider_name)

    # Sprint 2 primary/fallback env
    primary = os.getenv("COMMUNICATION_PRIMARY_PROVIDER", "").strip()
    if primary:
        return _build_provider(primary)

    return None


def get_provider_chain() -> list[BaseCommunicationAdapter]:
    """Return an ordered list of providers: [primary, fallback].

    Both are instantiated only if configured. Returns empty list
    when no providers are configured.
    """
    chain: list[BaseCommunicationAdapter] = []

    # Resolve primary
    legacy = os.getenv("COMMUNICATION_PROVIDER", "").strip()
    primary_name = legacy or os.getenv("COMMUNICATION_PRIMARY_PROVIDER", "").strip()
    fallback_name = os.getenv("COMMUNICATION_FALLBACK_PROVIDER", "").strip()

    # In legacy mode, COMMUNICATION_PROVIDER is the only provider
    if legacy:
        provider = _build_provider(legacy)
        if provider:
            chain.append(provider)
        return chain

    if primary_name:
        provider = _build_provider(primary_name)
        if provider:
            chain.append(provider)

    if fallback_name and fallback_name != primary_name:
        provider = _build_provider(fallback_name)
        if provider:
            chain.append(provider)

    return chain


def is_configured() -> bool:
    """Return True when at least one valid provider is configured."""
    return get_active_provider() is not None


def list_available_providers() -> list[str]:
    """Return all registered provider names."""
    return sorted(_PROVIDER_CLASSES.keys())


def get_config_summary() -> dict[str, str]:
    """Return masked configuration summary for all configured providers."""
    from app.integrations.communications.models import redact_credentials

    chain = get_provider_chain()
    if not chain:
        return {
            "provider": "(none configured)",
            "is_configured": "false",
            "fallback": "none",
        }

    result: dict[str, str] = {}
    for i, provider in enumerate(chain):
        role = "primary" if i == 0 else "fallback"
        name = provider.config.provider
        if provider.is_configured:
            masked = provider.config.redacted()
            result[f"{role}_provider"] = name
            result[f"{role}_status"] = "configured"
            # Include masked credentials (first 3 chars visible)
            for key, val in masked.items():
                result[f"{role}_{key}"] = val
        else:
            result[f"{role}_provider"] = name
            result[f"{role}_status"] = "not_configured"

    result["is_configured"] = "true" if chain[0].is_configured else "false"
    return result
