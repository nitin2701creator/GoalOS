"""Real Gmail REST API service (no Google SDK required).

Implements the :class:`GmailService` protocol over the shared HTTP client
against ``gmail.googleapis.com``. Authentication uses the OAuth
refresh-token grant so deployment needs only client credentials plus a
stored refresh token — no laptop process and no SDK.

The transport is injectable so tests never touch the network.
"""

from __future__ import annotations

import base64
import json
from dataclasses import fields
from datetime import datetime, timezone
from typing import Any

from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus
from app.integrations.email.models import (
    EmailFolder,
    EmailMessage,
    EmailSearchResult,
)
from app.integrations.exceptions import AuthenticationError
from app.integrations.http_client import HttpClient

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GmailTokenProvider:
    """Exchange a refresh token for a short-lived access token."""

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        self.client = client or HttpClient()
        self.client_id = client_id or self._env("GOALOS_GMAIL_CLIENT_ID") or ""
        self.client_secret = client_secret or self._env("GOALOS_GMAIL_CLIENT_SECRET") or ""
        self.refresh_token = refresh_token or self._env("GOALOS_GMAIL_REFRESH_TOKEN") or ""

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.refresh_token)

    def get_token(self) -> str:
        if not self.is_configured:
            raise AuthenticationError(
                "Gmail OAuth credentials are not configured "
                "(GOALOS_GMAIL_CLIENT_ID + GOALOS_GMAIL_REFRESH_TOKEN)"
            )
        response = self.client.fetch(
            _TOKEN_ENDPOINT,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=(
                "grant_type=refresh_token"
                f"&client_id={self.client_id}"
                f"&client_secret={self.client_secret}"
                f"&refresh_token={self.refresh_token}"
            ).encode(),
        )
        payload = json.loads(response.text)
        token = payload.get("access_token")
        if not token:
            raise AuthenticationError("Gmail token endpoint returned no access token")
        return str(token)

    @staticmethod
    def _env(name: str) -> str | None:
        import os

        value = os.environ.get(name)
        return value.strip() if value and value.strip() else None


class GmailRESTService:
    """Gmail API client implementing the provider-neutral protocol."""

    def __init__(
        self,
        client: HttpClient | None = None,
        token_provider: GmailTokenProvider | None = None,
    ) -> None:
        self.client = client or HttpClient()
        self.token_provider = token_provider or GmailTokenProvider()

    @property
    def is_configured(self) -> bool:
        return self.token_provider.is_configured

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token_provider.get_token()}"}

    def health_check(self) -> ConnectorHealth:
        if not self.is_configured:
            return ConnectorHealth(
                ConnectorHealthStatus.AUTHENTICATION_REQUIRED,
                "Gmail OAuth credentials are not configured",
            )
        return ConnectorHealth(ConnectorHealthStatus.HEALTHY)

    def list_folders(self) -> list[EmailFolder]:
        response = self.client.get(f"{_GMAIL_API}/labels", headers=self._auth_headers())
        payload = json.loads(response.text)
        return [
            EmailFolder(id=str(label.get("id", "")), name=str(label.get("name", "")))
            for label in payload.get("labels", [])
        ]

    def list_messages(self, folder_id: str | None = None) -> list[EmailMessage]:
        query: dict[str, Any] = {"maxResults": 20}
        if folder_id:
            query["labelIds"] = folder_id
        response = self.client.get(f"{_GMAIL_API}/messages", headers=self._auth_headers(), params=query)
        payload = json.loads(response.text)
        return [
            EmailMessage(id=str(item.get("id", "")), folder_id=folder_id)
            for item in payload.get("messages", [])
        ]

    def get_message(self, message_id: str) -> EmailMessage:
        response = self.client.get(
            f"{_GMAIL_API}/messages/{message_id}",
            headers=self._auth_headers(),
            params={"format": "metadata", "metadataHeaders": "From,To,Subject,Date"},
        )
        payload = json.loads(response.text)
        headers = {
            (header.get("name") or "").casefold(): header.get("value") or ""
            for header in payload.get("payload", {}).get("headers", [])
        }
        snippet = payload.get("snippet") or ""
        return EmailMessage(
            id=message_id,
            subject=headers.get("subject", ""),
            sender=headers.get("from") or None,
            recipients=tuple(
                part.strip() for part in (headers.get("to") or "").split(",") if part.strip()
            ),
            body_text=snippet,
            received_at=self._parse_date(headers.get("date")),
        )

    def search_messages(self, query: str) -> EmailSearchResult:
        response = self.client.get(
            f"{_GMAIL_API}/messages",
            headers=self._auth_headers(),
            params={"q": query, "maxResults": 20},
        )
        payload = json.loads(response.text)
        messages = [
            EmailMessage(id=str(item.get("id", "")), body_text=item.get("snippet"))
            for item in payload.get("messages", [])
        ]
        return EmailSearchResult(
            query=query,
            messages=tuple(messages),
            total_count=len(messages),
        )

    def create_draft(self, message: EmailMessage) -> EmailMessage:
        raw = self._build_raw(message)
        response = self.client.fetch(
            f"{_GMAIL_API}/drafts",
            method="POST",
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            body=json.dumps({"message": {"raw": raw}}).encode(),
        )
        payload = json.loads(response.text)
        draft_id = payload.get("id") or payload.get("message", {}).get("id") or ""
        return EmailMessage(id=str(draft_id), subject=message.subject)

    def send_message(self, message: EmailMessage) -> EmailMessage:
        raw = self._build_raw(message)
        response = self.client.fetch(
            f"{_GMAIL_API}/messages/send",
            method="POST",
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            body=json.dumps({"raw": raw}).encode(),
        )
        payload = json.loads(response.text)
        return EmailMessage(
            id=str(payload.get("id", "")),
            subject=message.subject,
            recipients=message.recipients,
            sent_at=datetime.now(timezone.utc),
        )

    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage:
        raise NotImplementedError("Gmail reply requires a fully fetched thread")

    @staticmethod
    def _build_raw(message: EmailMessage) -> str:
        """Build a base64url MIME message from an EmailMessage."""
        recipients = ", ".join(message.recipients) or ""
        lines = [
            f"From: {message.sender or ''}",
            f"To: {recipients}",
            f"Subject: {message.subject}",
            "MIME-Version: 1.0",
            "Content-Type: text/plain; charset=UTF-8",
            "Content-Transfer-Encoding: 8bit",
            "",
            message.body_text or "",
        ]
        raw = "\r\n".join(lines).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(value)
        except Exception:  # noqa: BLE001 - malformed dates are ignored
            return None
        return parsed.astimezone() if parsed.tzinfo else parsed


def message_from_dict(values: dict[str, Any]) -> EmailMessage:
    """Build an EmailMessage from a plain mapping, ignoring unknown keys."""
    allowed = {field.name for field in fields(EmailMessage)}
    kwargs = {key: value for key, value in values.items() if key in allowed}
    recipients = kwargs.pop("recipients", ())
    if isinstance(recipients, list):
        recipients = tuple(recipients)
    kwargs["recipients"] = recipients
    return EmailMessage(**kwargs)
