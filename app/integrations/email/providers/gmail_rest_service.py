"""Real Gmail REST API service (no Google SDK required).

Implements the :class:`GmailService` protocol over the shared HTTP client
against ``gmail.googleapis.com``. Authentication uses the shared Google
OAuth refresh-token grant (``app.integrations.google_auth``) so deployment
needs only client credentials plus a stored refresh token — no laptop
process and no SDK.

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
    AttachmentMetadata,
    EmailFolder,
    EmailMessage,
    EmailSearchResult,
)
from app.integrations.google_auth import GoogleOAuthTokenProvider
from app.integrations.http_client import HttpClient

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


class GmailTokenProvider:
    """Gmail access-token provider built on the shared Google OAuth service.

    Reads ``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET`` /
    ``GOOGLE_REFRESH_TOKEN`` with the legacy ``GOALOS_GMAIL_*`` names as
    fallbacks. Access tokens are cached in memory only and never logged.
    """

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        self._provider = GoogleOAuthTokenProvider(
            client=client or HttpClient(),
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            scope=_GMAIL_SCOPE,
        )

    @property
    def is_configured(self) -> bool:
        return self._provider.is_configured

    def get_token(self) -> str:
        return self._provider.get_token()

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
        self.token_provider = token_provider or GmailTokenProvider(client=self.client)

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

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
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
        headers = self._headers(payload)
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

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------
    def list_threads(self, query: str = "", max_results: int = 20) -> list[EmailMessage]:
        params: dict[str, Any] = {"maxResults": max_results}
        if query:
            params["q"] = query
        response = self.client.get(f"{_GMAIL_API}/threads", headers=self._auth_headers(), params=params)
        payload = json.loads(response.text)
        return [
            EmailMessage(id=str(item.get("id", "")), body_text=item.get("snippet"))
            for item in payload.get("threads", [])
        ]

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        response = self.client.get(
            f"{_GMAIL_API}/threads/{thread_id}",
            headers=self._auth_headers(),
            params={"format": "full"},
        )
        payload = json.loads(response.text)
        messages = []
        for item in payload.get("messages", []):
            headers = self._headers(item)
            messages.append(
                {
                    "id": item.get("id"),
                    "subject": headers.get("subject", ""),
                    "sender": headers.get("from"),
                    "snippet": item.get("snippet"),
                }
            )
        return {
            "thread_id": thread_id,
            "history_id": payload.get("historyId"),
            "messages": messages,
            "total": len(messages),
        }

    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage:
        """Reply to the thread containing ``message_id`` via the send API."""
        original = self.client.get(
            f"{_GMAIL_API}/messages/{message_id}",
            headers=self._auth_headers(),
            params={
                "format": "metadata",
                "metadataHeaders": "From,To,Subject,Message-ID,References,In-Reply-To",
            },
        )
        original_payload = json.loads(original.text)
        original_headers = self._headers(original_payload)
        thread_id = original_payload.get("threadId") or message_id

        recipients = message.recipients or (
            tuple(part.strip() for part in (original_headers.get("from") or "").split(",") if part.strip())
        )
        subject = message.subject or f"Re: {original_headers.get('subject', '')}"
        references = self._references(original_headers)
        reply_message = EmailMessage(
            id="",
            subject=subject,
            recipients=recipients,
            body_text=message.body_text or "",
            in_reply_to=original_headers.get("message-id") or message_id,
        )
        raw = self._build_raw(reply_message, references=references)
        response = self.client.fetch(
            f"{_GMAIL_API}/messages/send",
            method="POST",
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            body=json.dumps({"raw": raw, "threadId": thread_id}).encode(),
        )
        payload = json.loads(response.text)
        return EmailMessage(
            id=str(payload.get("id", "")),
            subject=subject,
            recipients=recipients,
            in_reply_to=original_headers.get("message-id") or message_id,
            sent_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------
    def list_attachments(self, message_id: str) -> list[AttachmentMetadata]:
        response = self.client.get(
            f"{_GMAIL_API}/messages/{message_id}",
            headers=self._auth_headers(),
            params={"format": "full"},
        )
        payload = json.loads(response.text)
        parts: list[dict[str, Any]] = []

        def walk(part: dict[str, Any]) -> None:
            if isinstance(part.get("body"), dict) and part["body"].get("attachmentId"):
                parts.append(part)
            for child in part.get("parts", []) or []:
                walk(child)

        walk(payload.get("payload") or {})
        return [
            AttachmentMetadata(
                filename=str(part.get("filename") or "attachment"),
                content_type=part.get("mimeType"),
                size=int(part.get("body", {}).get("size") or 0) or None,
                content_id=part.get("headers", {}).get("Content-ID") if isinstance(part.get("headers"), dict) else None,
            )
            for part in parts
        ]

    def get_attachment(self, message_id: str, attachment_id: str) -> dict[str, Any]:
        response = self.client.get(
            f"{_GMAIL_API}/messages/{message_id}/attachments/{attachment_id}",
            headers=self._auth_headers(),
        )
        payload = json.loads(response.text)
        data = payload.get("data") or ""
        try:
            content = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        except (ValueError, TypeError):
            content = b""
        return {
            "attachment_id": attachment_id,
            "size": payload.get("size"),
            "size_bytes": len(content),
            "content_base64": base64.b64encode(content).decode(),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _headers(payload: dict[str, Any]) -> dict[str, str]:
        return {
            (header.get("name") or "").casefold(): header.get("value") or ""
            for header in payload.get("payload", {}).get("headers", [])
        }

    @staticmethod
    def _references(headers: dict[str, str]) -> str:
        parts: list[str] = []
        if headers.get("references"):
            parts.append(headers["references"])
        if headers.get("in-reply-to"):
            parts.append(headers["in-reply-to"])
        if headers.get("message-id"):
            parts.append(headers["message-id"])
        return " ".join(parts)

    def _build_raw(self, message: EmailMessage, *, references: str = "") -> str:
        """Build a base64url MIME message from an EmailMessage."""
        recipients = ", ".join(message.recipients) or ""
        lines = [
            f"From: {message.sender or ''}",
            f"To: {recipients}",
            f"Subject: {message.subject}",
            "MIME-Version: 1.0",
            "Content-Type: text/plain; charset=UTF-8",
            "Content-Transfer-Encoding: 8bit",
        ]
        if message.in_reply_to:
            lines.append(f"In-Reply-To: {message.in_reply_to}")
        if references:
            lines.append(f"References: {references}")
        lines += ["", message.body_text or ""]
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
