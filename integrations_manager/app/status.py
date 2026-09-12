"""Canonical connection-state vocabulary for the Integrations Manager.

Every integration surfaces exactly one of these states. The UI maps each
state to a distinct label and color; the backend derives states that
involve token expiry or disabled integrations on top of the last
authoritative status stored by the routers.

Vocabulary:
    not_configured     — nothing stored, nothing tested.
    configured         — API-key credentials stored (no live test yet).
    auth_required      — OAuth provider that still needs authorization.
    connected          — live connection verified (or OAuth completed).
    expired            — stored token expired; reconnect required.
    unreachable        — remote service unreachable on last test.
    auth_failed        — remote rejected the stored credentials.
    invalid_config     — required configuration is missing/invalid.
    api_unavailable    — provider API reported an outage-style failure.
    error              — unexpected failure during the last test.
    disabled           — integration intentionally disabled.

Failure states (unhealthy) are grouped by :func:`is_unhealthy`.
"""
from __future__ import annotations

NOT_CONFIGURED = "not_configured"
CONFIGURED = "configured"
AUTH_REQUIRED = "auth_required"
CONNECTED = "connected"
EXPIRED = "expired"
UNREACHABLE = "unreachable"
AUTH_FAILED = "auth_failed"
INVALID_CONFIG = "invalid_config"
API_UNAVAILABLE = "api_unavailable"
ERROR = "error"
DISABLED = "disabled"

#: States that mean the integration is not working right now.
UNHEALTHY_STATES = frozenset({
    EXPIRED,
    UNREACHABLE,
    AUTH_FAILED,
    INVALID_CONFIG,
    API_UNAVAILABLE,
    ERROR,
})

#: States test providers may report via ``TestResult.status``.
PROVIDER_TEST_STATES = frozenset({
    CONNECTED,
    AUTH_FAILED,
    UNREACHABLE,
    INVALID_CONFIG,
    API_UNAVAILABLE,
    ERROR,
})

#: States the frontend must render distinctly.
KNOWN_STATES = frozenset({
    NOT_CONFIGURED,
    CONFIGURED,
    AUTH_REQUIRED,
    CONNECTED,
    EXPIRED,
    UNREACHABLE,
    AUTH_FAILED,
    INVALID_CONFIG,
    API_UNAVAILABLE,
    ERROR,
    DISABLED,
})


def is_unhealthy(state: str) -> bool:
    """Return True when ``state`` means the integration needs attention."""
    return state in UNHEALTHY_STATES