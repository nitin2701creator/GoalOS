"""Credential storage service.

Provides encrypted storage and retrieval of integration credentials,
environment variable hydration, and connection testing for each integration.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.credential import EncryptedCredential
from app.services.credential_encryption import decrypt_value, encrypt_value, mask_value

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field definitions per integration
# Each integration defines what fields it accepts, their types, and how
# to hydrate them into environment variables.
# ---------------------------------------------------------------------------

INTEGRATION_FIELDS: dict[str, list[dict[str, Any]]] = {
    "woocommerce": [
        {"key": "store_url", "label": "Store URL", "type": "url", "env": "GOALOS_WOO_URL"},
        {"key": "consumer_key", "label": "Consumer Key", "type": "secret", "env": "GOALOS_WOO_CONSUMER_KEY"},
        {"key": "consumer_secret", "label": "Consumer Secret", "type": "secret", "env": "GOALOS_WOO_CONSUMER_SECRET"},
    ],
    "google_analytics": [
        {"key": "client_id", "label": "Client ID", "type": "text", "env": "GOOGLE_CLIENT_ID"},
        {"key": "client_secret", "label": "Client Secret", "type": "secret", "env": "GOOGLE_CLIENT_SECRET"},
        {"key": "refresh_token", "label": "Refresh Token", "type": "secret", "env": "GOOGLE_REFRESH_TOKEN"},
        {"key": "property_id", "label": "GA4 Property ID", "type": "text", "env": "GOALOS_GA4_PROPERTY_ID"},
        {"key": "redirect_uri", "label": "OAuth Redirect URI", "type": "url", "env": "GOOGLE_REDIRECT_URI"},
    ],
    "gmail": [
        {"key": "client_id", "label": "Client ID", "type": "text", "env": "GOOGLE_CLIENT_ID"},
        {"key": "client_secret", "label": "Client Secret", "type": "secret", "env": "GOOGLE_CLIENT_SECRET"},
        {"key": "refresh_token", "label": "Refresh Token", "type": "secret", "env": "GOOGLE_REFRESH_TOKEN"},
    ],
    "calendar": [
        {"key": "client_id", "label": "Client ID", "type": "text", "env": "GOOGLE_CLIENT_ID"},
        {"key": "client_secret", "label": "Client Secret", "type": "secret", "env": "GOOGLE_CLIENT_SECRET"},
        {"key": "refresh_token", "label": "Refresh Token", "type": "secret", "env": "GOOGLE_REFRESH_TOKEN"},
    ],
    "drive": [
        {"key": "client_id", "label": "Client ID", "type": "text", "env": "GOOGLE_CLIENT_ID"},
        {"key": "client_secret", "label": "Client Secret", "type": "secret", "env": "GOOGLE_CLIENT_SECRET"},
        {"key": "refresh_token", "label": "Refresh Token", "type": "secret", "env": "GOOGLE_REFRESH_TOKEN"},
    ],
    "meta_social": [
        {"key": "page_access_token", "label": "Page Access Token", "type": "secret", "env": "GOALOS_META_PAGE_ACCESS_TOKEN"},
    ],
    "meta_ads": [
        {"key": "access_token", "label": "Access Token", "type": "secret", "env": "GOALOS_META_ACCESS_TOKEN"},
        {"key": "ad_account_id", "label": "Ad Account ID", "type": "text", "env": "GOALOS_META_AD_ACCOUNT_ID"},
    ],
    "linkedin": [
        {"key": "access_token", "label": "Access Token", "type": "secret", "env": "LINKEDIN_ACCESS_TOKEN"},
        {"key": "organization_id", "label": "Organization ID", "type": "text", "env": "LINKEDIN_ORGANIZATION_ID"},
    ],
    "twitter": [
        {"key": "bearer_token", "label": "Bearer Token", "type": "secret", "env": "GOALOS_X_BEARER_TOKEN"},
    ],
    "reddit": [
        {"key": "access_token", "label": "Access Token", "type": "secret", "env": "GOALOS_REDDIT_ACCESS_TOKEN"},
    ],
    "twenty": [
        {"key": "base_url", "label": "Twenty Base URL", "type": "url", "env": "GOALOS_TWENTY_BASE_URL"},
        {"key": "api_key", "label": "Twenty API Key", "type": "secret", "env": "GOALOS_TWENTY_API_KEY"},
    ],
    "n8n": [
        {"key": "base_url", "label": "n8n Base URL", "type": "url", "env": "GOALOS_N8N_BASE_URL"},
        {"key": "api_key", "label": "n8n API Key", "type": "secret", "env": "GOALOS_N8N_API_KEY"},
    ],
}

# Integrations that share Google OAuth credentials
_GOOGLE_SHARED = {"google_analytics", "gmail", "calendar", "drive"}


class CredentialService:
    """Encrypted credential storage and environment hydration."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    def save(self, integration: str, values: dict[str, str]) -> list[dict[str, Any]]:
        """Save encrypted credentials for one integration.

        Returns the masked field list after saving.
        """
        fields = INTEGRATION_FIELDS.get(integration, [])
        field_map = {f["key"]: f for f in fields}

        for key, value in values.items():
            if key not in field_map or not value:
                continue
            existing = (
                self.db.query(EncryptedCredential)
                .filter_by(integration=integration, field_key=key)
                .first()
            )
            token = encrypt_value(value)
            hint = mask_value(value)
            if existing:
                existing.encrypted_value = token
                existing.display_hint = hint
            else:
                self.db.add(
                    EncryptedCredential(
                        integration=integration,
                        field_key=key,
                        encrypted_value=token,
                        display_hint=hint,
                    )
                )
        self.db.commit()

        # Hydrate environment variables so running connectors pick them up
        self._hydrate_env(integration)

        return self.get_masked(integration)

    def get_masked(self, integration: str) -> list[dict[str, Any]]:
        """Return field definitions with masked values (never plaintext)."""
        fields = INTEGRATION_FIELDS.get(integration, [])
        stored = {
            c.field_key: c
            for c in self.db.query(EncryptedCredential)
            .filter_by(integration=integration)
            .all()
        }
        result = []
        for f in fields:
            entry = stored.get(f["key"])
            result.append({
                "key": f["key"],
                "label": f["label"],
                "type": f["type"],
                "has_value": entry is not None,
                "display_hint": entry.display_hint if entry else None,
                "env_var": f["env"],
            })
        return result

    def get_plaintext(self, integration: str) -> dict[str, str]:
        """Return decrypted values (internal use only, never exposed via API)."""
        rows = (
            self.db.query(EncryptedCredential)
            .filter_by(integration=integration)
            .all()
        )
        return {r.field_key: decrypt_value(r.encrypted_value) for r in rows}

    def delete(self, integration: str) -> None:
        """Remove all stored credentials for an integration."""
        self.db.query(EncryptedCredential).filter_by(integration=integration).delete()
        self.db.commit()
        # Unset the environment variables
        fields = INTEGRATION_FIELDS.get(integration, [])
        for f in fields:
            env_var = f["env"]
            # Only unset if no other integration shares this env var
            if not self._env_shared_by_others(integration, env_var):
                os.environ.pop(env_var, None)

    def clear_all(self) -> None:
        """Remove every stored credential."""
        self.db.query(EncryptedCredential).delete()
        self.db.commit()

    # ------------------------------------------------------------------
    # Environment hydration
    # ------------------------------------------------------------------
    def _hydrate_env(self, integration: str) -> None:
        """Write stored credentials into process environment variables."""
        fields = INTEGRATION_FIELDS.get(integration, [])
        values = self.get_plaintext(integration)
        for f in fields:
            val = values.get(f["key"])
            if val:
                os.environ[f["env"]] = val

    def hydrate_all(self) -> int:
        """Rehydrate all stored credentials into the environment.

        Called at application startup. Returns the number of integrations
        that were hydrated.
        """
        integrations = (
            self.db.query(EncryptedCredential.integration)
            .distinct()
            .all()
        )
        count = 0
        for (name,) in integrations:
            self._hydrate_env(name)
            count += 1
        return count

    def _env_shared_by_others(self, exclude: str, env_var: str) -> bool:
        """Check if another integration also writes to this env var."""
        for name, fields in INTEGRATION_FIELDS.items():
            if name == exclude:
                continue
            for f in fields:
                if f["env"] == env_var:
                    return True
        return False

    def list_integrations_with_status(self) -> list[dict[str, Any]]:
        """List all integrations that support credential configuration,
        with their stored credential status."""
        result = []
        for name, fields in INTEGRATION_FIELDS.items():
            stored = (
                self.db.query(EncryptedCredential)
                .filter_by(integration=name)
                .count()
            )
            result.append({
                "name": name,
                "display_name": _display_name(name),
                "fields_count": len(fields),
                "credentials_stored": stored,
                "is_configured": stored > 0,
            })
        return result


def _display_name(name: str) -> str:
    """Human-readable display name for an integration."""
    names = {
        "woocommerce": "WooCommerce",
        "google_analytics": "Google Analytics 4",
        "gmail": "Gmail",
        "calendar": "Google Calendar",
        "drive": "Google Drive",
        "meta_social": "Meta / Facebook",
        "meta_ads": "Meta Ads",
        "linkedin": "LinkedIn",
        "twitter": "X / Twitter",
        "reddit": "Reddit",
        "twenty": "Twenty CRM",
        "n8n": "n8n Automation",
    }
    return names.get(name, name.replace("_", " ").title())
