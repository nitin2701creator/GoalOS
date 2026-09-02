"""WhatsApp provider factory for GoalOS.

Selects the active provider from WHATSAPP_PROVIDER environment variable
and instantiates the correct adapter. Returns None when no provider is
configured rather than crashing.

Supported providers:
    wacrm  — WACRM (Meta WhatsApp Business API, primary)
    openwa — OpenWA (WhatsApp Web, secondary)
    meta   — Meta Cloud API (legacy, same as wacrm)
    auto   — Use WACRM if configured, else OpenWA if configured
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.integrations.whatsapp.base import BaseWhatsAppAdapter

logger = logging.getLogger(__name__)

#: Registry of known providers and their adapter classes.
_PROVIDER_CLASSES: dict[str, str] = {
    "wacrm": "app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter",
    "openwa": "app.integrations.whatsapp.openwa_adapter.OpenWAAdapter",
    "meta": "app.integrations.whatsapp.meta_adapter.MetaWhatsAppAdapter",
}


def _build_provider(name: str) -> BaseWhatsAppAdapter | None:
    """Instantiate a single provider by name, or None."""
    name = name.strip().lower()
    if not name:
        return None
    dotted = _PROVIDER_CLASSES.get(name)
    if dotted is None:
        logger.warning("Unknown WhatsApp provider: %s", name)
        return None
    module_path, _, class_name = dotted.rpartition(".")
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


def get_active_provider() -> BaseWhatsAppAdapter | None:
    """Return the active provider based on WHATSAPP_PROVIDER env.

    Returns None when no provider is configured.
    
    'auto' mode: use WACRM if configured, else OpenWA if configured.
    """
    provider_name = os.getenv("WHATSAPP_PROVIDER", "").strip()
    if not provider_name:
        return None
    
    if provider_name.lower() == "auto":
        return _resolve_auto_provider()
    
    return _build_provider(provider_name)


def _resolve_auto_provider() -> BaseWhatsAppAdapter | None:
    """Auto-select: WACRM preferred, OpenWA fallback."""
    # Try WACRM first (production-grade Meta API)
    wacrm = _build_provider("wacrm")
    if wacrm and wacrm.is_configured:
        return wacrm
    # Fall back to OpenWA (WhatsApp Web)
    openwa = _build_provider("openwa")
    if openwa and openwa.is_configured:
        return openwa
    logger.warning("Auto provider mode: no configured provider found")
    return None


def is_configured() -> bool:
    """Return True when a valid provider is configured."""
    provider = get_active_provider()
    return provider is not None and provider.is_configured


def list_available_providers() -> list[str]:
    """Return all registered provider names."""
    return sorted(_PROVIDER_CLASSES.keys())


def get_all_provider_status() -> dict[str, Any]:
    """Return status of all registered providers (no secrets)."""
    result: dict[str, Any] = {
        "available_providers": list_available_providers(),
        "active_provider": None,
        "providers": {},
    }
    active = get_active_provider()
    if active:
        result["active_provider"] = active.name
    for name in _PROVIDER_CLASSES:
        provider = _build_provider(name)
        if provider:
            result["providers"][name] = {
                "configured": provider.is_configured,
                "status": "ready" if provider.is_configured else "not_configured",
            }
    return result


def get_config_summary() -> dict[str, str]:
    """Return masked configuration summary for the active provider."""
    from app.integrations.whatsapp.models import redact_whatsapp_config

    provider_name = os.getenv("WHATSAPP_PROVIDER", "").strip()
    if not provider_name:
        return {
            "provider": "(none configured)",
            "is_configured": "false",
        }

    provider = get_active_provider()
    if provider is None:
        return {
            "provider": provider_name,
            "is_configured": "false",
        }

    masked = provider.config.redacted()
    return masked
