"""Live integration smoke test for GoalOS's seven core real-world integrations.

For each integration the script performs ONE harmless authenticated read:

- Gmail:      read-only message search (never sends)
- Calendar:   list calendars (never creates events)
- Drive:      search file metadata (never uploads)
- Twenty:     list people, limit 1 (never creates records)
- WooCommerce: list products, per_page 1 (never creates orders)
- LinkedIn:   read organization metadata (never publishes)
- n8n:        list workflows, limit 1 (never triggers a workflow)

Each integration prints exactly one status line:

    NOT CONFIGURED | PASS | AUTH FAILED | PERMISSION DENIED | RATE LIMITED | FAILED

The exit code is non-zero only if an integration IS configured but fails.
An environment with no credentials at all exits 0 (everything reports
NOT CONFIGURED). No destructive operation is ever performed.

Usage:
    python scripts/live_integration_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow invocation as ``python scripts/live_integration_smoke.py`` from any
# working directory: make the repository root importable.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.permissions import Permission
from app.integrations.email.providers.gmail_provider import GmailProvider
from app.integrations.exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.google_calendar import GoogleCalendarConnector
from app.integrations.google_drive import GoogleDriveConnector
from app.integrations.linkedin import LinkedInConnector
from app.integrations.n8n import N8NConnector
from app.integrations.twenty import TwentyConnector
from app.integrations.woocommerce import WooCommerceConnector

#: (display name, connector factory, capability, params)
_CHECKS: list[tuple[str, object, str, dict]] = [
    (
        "gmail",
        GmailProvider(),
        "gmail.search_messages",
        {"query": "in:inbox newer_than:30d"},
    ),
    (
        "calendar",
        GoogleCalendarConnector(),
        "calendar.list_calendars",
        {},
    ),
    (
        "drive",
        GoogleDriveConnector(),
        "drive.search",
        {"query": "trashed = false", "page_size": 5},
    ),
    (
        "twenty",
        TwentyConnector(),
        "twenty.list_people",
        {"limit": 1},
    ),
    (
        "woocommerce",
        WooCommerceConnector(),
        "woocommerce.list_products",
        {"per_page": 1},
    ),
    (
        "linkedin",
        LinkedInConnector(),
        "linkedin.get_organization",
        {},
    ),
    (
        "n8n",
        N8NConnector(),
        "n8n.list_workflows",
        {"limit": 1},
    ),
]


def _status_for(connector: object, capability: str, params: dict) -> str:
    """Run one harmless read and map the outcome to a single status word."""
    if not getattr(connector, "is_configured", False):
        return "NOT CONFIGURED"
    permissions = getattr(connector, "CAPABILITY_PERMISSIONS", {}).get(capability)
    granted = {permissions} if permissions is not None else {Permission.READ_WEBSITE}
    try:
        connector.execute(capability, params, permissions=granted)
    except PermissionDeniedError:
        return "PERMISSION DENIED"
    except AuthenticationError as exc:
        return "AUTH FAILED" if "AUTHENTICATION_FAILED" in str(exc) else "FAILED"
    except RateLimitError:
        return "RATE LIMITED"
    except Exception:  # noqa: BLE001 - status reporting, not error masking
        return "FAILED"
    return "PASS"


def main() -> int:
    results: list[tuple[str, str]] = []
    for name, connector, capability, params in _CHECKS:
        status = _status_for(connector, capability, params)
        results.append((name, status))
        print(f"{name}: {status}")

    configured_failures = [
        name for name, status in results if status not in ("NOT CONFIGURED", "PASS")
    ]
    print()
    print(f"integrations checked: {len(results)}")
    print(f"configured: {sum(1 for _, s in results if s != 'NOT CONFIGURED')}")
    print(f"not configured: {sum(1 for _, s in results if s == 'NOT CONFIGURED')}")
    if configured_failures:
        print(f"configured but FAILED: {', '.join(configured_failures)}")
        return 1
    print("configured but FAILED: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
