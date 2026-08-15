"""Google Drive integration via the Drive API v3.

``GoogleDriveConnector`` talks to ``www.googleapis.com/drive/v3`` (and the
``/upload/drive/v3`` media endpoint) over the shared HTTP client using the
shared Google OAuth token service. It supports search, metadata retrieval,
downloads, uploads, folder creation, moves, deletes, and folder listing.

Honesty contract:

- Missing Google OAuth configuration reports ``Not Configured``.
- HTTP 401 maps to :class:`AuthenticationError` (``AUTHENTICATION_FAILED``).
- HTTP 403 maps to :class:`PermissionDeniedError` (``PERMISSION_DENIED``).
- HTTP 429 maps to :class:`RateLimitError` (``RATE_LIMITED``).
- Binary file contents are never stored in the integration registry; a
  download returns base64 content only up to a bounded cap with an honest
  ``truncated`` flag.
- Reads require ``READ_DRIVE``; uploads/moves/deletes require
  ``WRITE_DRIVE`` (a dangerous permission never granted implicitly).
"""

from __future__ import annotations

import base64
import json
from typing import Any, ClassVar

from app.agents.permissions import Permission
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.google_auth import (
    GoogleOAuthTokenProvider,
    auth_headers,
    decode_error_payload,
)
from app.integrations.http_client import HttpClient, HttpStatusError
from app.integrations.integration_connector import IntegrationConnector

_DRIVE_API = "https://www.googleapis.com/drive/v3"
_DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
_OAUTH_SCOPE = "https://www.googleapis.com/auth/drive.file"

_FOLDER_MIME = "application/vnd.google-apps.folder"

#: Default cap on downloaded file content returned in execution results.
DEFAULT_MAX_DOWNLOAD_BYTES = 1024 * 1024

_READ_CAPABILITIES = frozenset(
    {
        "drive.health",
        "drive.search",
        "drive.get_file",
        "drive.download_file",
        "drive.list_folder",
    }
)


class GoogleDriveConnector(IntegrationConnector):
    """Google Drive connector for files, folders, and media."""

    required_env_vars: tuple[str, ...] = (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "GOOGLE_REFRESH_TOKEN",
    )
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        capability: (
            Permission.READ_DRIVE
            if capability in _READ_CAPABILITIES
            else Permission.WRITE_DRIVE
        )
        for capability in (
            "drive.health",
            "drive.search",
            "drive.get_file",
            "drive.download_file",
            "drive.upload_file",
            "drive.create_folder",
            "drive.move_file",
            "drive.delete_file",
            "drive.list_folder",
        )
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        token_provider: GoogleOAuthTokenProvider | None = None,
    ) -> None:
        super().__init__(
            name="drive",
            description="Google Drive API integration",
        )
        self.client = client or HttpClient()
        self.token_provider = token_provider or GoogleOAuthTokenProvider(
            client=self.client, scope=_OAUTH_SCOPE
        )

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "drive.health",
            "drive.search",
            "drive.get_file",
            "drive.download_file",
            "drive.upload_file",
            "drive.create_folder",
            "drive.move_file",
            "drive.delete_file",
            "drive.list_folder",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        missing = self.token_provider.missing_configuration()
        if missing:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                f"missing environment configuration: {', '.join(missing)}",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "drive.health":
            return self._health()
        if capability == "drive.search":
            return self._search(params)
        if capability == "drive.get_file":
            return self._get_file(params)
        if capability == "drive.download_file":
            return self._download_file(params)
        if capability == "drive.upload_file":
            return self._upload_file(params)
        if capability == "drive.create_folder":
            return self._create_folder(params)
        if capability == "drive.move_file":
            return self._move_file(params)
        if capability == "drive.delete_file":
            return self._delete_file(params)
        if capability == "drive.list_folder":
            return self._list_folder(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        status, message = self._configuration_status()
        return {
            "integration": "drive",
            "status": status.value,
            "configured": status.value == "Healthy",
            "message": message,
        }

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {
            "pageSize": int(params.get("page_size") or 50),
            "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,parents)",
        }
        if params.get("query"):
            query["q"] = params["query"]
        response = self._fetch("GET", f"{_DRIVE_API}/files", params=query)
        payload = self._decode(response, path="files")
        files = [item for item in (payload.get("files") or []) if isinstance(item, dict)]
        return {
            "total": len(files),
            "next_page_token": payload.get("nextPageToken"),
            "items": [self._metadata(item) for item in files],
        }

    def _list_folder(self, params: dict[str, Any]) -> dict[str, Any]:
        folder_id = params.get("folder_id")
        if not folder_id:
            raise ValueError("folder_id is required for drive.list_folder")
        query: dict[str, Any] = {
            "pageSize": int(params.get("page_size") or 100),
            "q": f"'{folder_id}' in parents",
            "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime)",
        }
        response = self._fetch("GET", f"{_DRIVE_API}/files", params=query)
        payload = self._decode(response, path="files")
        files = [item for item in (payload.get("files") or []) if isinstance(item, dict)]
        return {
            "folder_id": folder_id,
            "total": len(files),
            "items": [self._metadata(item) for item in files],
        }

    def _get_file(self, params: dict[str, Any]) -> dict[str, Any]:
        file_id = params.get("file_id")
        if not file_id:
            raise ValueError("file_id is required for drive.get_file")
        response = self._fetch(
            "GET",
            f"{_DRIVE_API}/files/{self._quote(file_id)}",
            params={"fields": "id,name,mimeType,size,modifiedTime,parents,trashed"},
        )
        payload = self._decode(response, path=f"files/{file_id}")
        return {"file": self._metadata(payload)}

    def _download_file(self, params: dict[str, Any]) -> dict[str, Any]:
        file_id = params.get("file_id")
        if not file_id:
            raise ValueError("file_id is required for drive.download_file")
        meta_response = self._fetch(
            "GET",
            f"{_DRIVE_API}/files/{self._quote(file_id)}",
            params={"fields": "id,name,mimeType,size,modifiedTime"},
        )
        metadata = self._decode(meta_response, path=f"files/{file_id}")
        max_bytes = int(params.get("max_bytes") or DEFAULT_MAX_DOWNLOAD_BYTES)
        response = self._fetch(
            "GET",
            f"{_DRIVE_API}/files/{self._quote(file_id)}",
            params={"alt": "media"},
        )
        content = response.body
        truncated = len(content) > max_bytes
        if truncated:
            content = content[:max_bytes]
        return {
            "file": self._metadata(metadata),
            "size_bytes": len(content),
            "content_base64": base64.b64encode(content).decode(),
            "truncated": truncated,
        }

    def _upload_file(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not name:
            raise ValueError("name is required for drive.upload_file")
        content = self._content_bytes(params)
        query: dict[str, Any] = {"uploadType": "media"}
        if params.get("parents"):
            query["addParents"] = ",".join(params["parents"])
        response = self._fetch(
            "POST",
            f"{_DRIVE_UPLOAD_API}/files",
            params=query,
            headers={"Content-Type": params.get("content_type") or "application/octet-stream"},
            body=content,
        )
        payload = self._decode(response, path="upload/files")
        return {"uploaded": True, "file": self._metadata(payload)}

    def _create_folder(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not name:
            raise ValueError("name is required for drive.create_folder")
        body: dict[str, Any] = {"name": name, "mimeType": _FOLDER_MIME}
        if params.get("parents"):
            body["parents"] = params["parents"]
        response = self._fetch(
            "POST",
            f"{_DRIVE_API}/files",
            headers={"Content-Type": "application/json"},
            body=json.dumps(body).encode(),
        )
        payload = self._decode(response, path="files")
        return {"created": True, "folder": self._metadata(payload)}

    def _move_file(self, params: dict[str, Any]) -> dict[str, Any]:
        file_id = params.get("file_id")
        if not file_id:
            raise ValueError("file_id is required for drive.move_file")
        query: dict[str, Any] = {}
        if params.get("add_parents"):
            query["addParents"] = ",".join(params["add_parents"])
        if params.get("remove_parents"):
            query["removeParents"] = ",".join(params["remove_parents"])
        if not query:
            raise ValueError("add_parents or remove_parents is required for drive.move_file")
        response = self._fetch(
            "PATCH",
            f"{_DRIVE_API}/files/{self._quote(file_id)}",
            params=query,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
        payload = self._decode(response, path=f"files/{file_id}")
        return {"moved": True, "file": self._metadata(payload)}

    def _delete_file(self, params: dict[str, Any]) -> dict[str, Any]:
        file_id = params.get("file_id")
        if not file_id:
            raise ValueError("file_id is required for drive.delete_file")
        response = self._fetch(
            "DELETE", f"{_DRIVE_API}/files/{self._quote(file_id)}"
        )
        self._decode(response, path=f"files/{file_id}", allow_empty=True)
        return {"deleted": True, "file_id": file_id}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _content_bytes(params: dict[str, Any]) -> bytes:
        """Return the upload payload from ``content`` or ``content_base64``."""
        if params.get("content_base64"):
            return base64.b64decode(params["content_base64"])
        if params.get("content") is not None:
            return str(params["content"]).encode()
        raise ValueError("content or content_base64 is required for drive.upload_file")

    @staticmethod
    def _metadata(item: dict[str, Any]) -> dict[str, Any]:
        """Normalize Drive file metadata (never binary contents)."""
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "mime_type": item.get("mimeType"),
            "size": item.get("size"),
            "modified_time": item.get("modifiedTime"),
            "parents": item.get("parents"),
            "trashed": item.get("trashed"),
        }

    def _fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue one authenticated request with stable error mapping."""
        request_headers = {**auth_headers(self.token_provider), **(headers or {})}
        try:
            return self.client.fetch(
                url,
                method=method,
                headers=request_headers,
                body=body,
                params=params,
            )
        except HttpStatusError as exc:
            status = int(exc.status)
            if status == 401:
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: Google Drive returned HTTP 401 at "
                    f"{exc.url} (refresh token invalid or expired)"
                ) from exc
            if status == 403:
                raise PermissionDeniedError(
                    f"PERMISSION_DENIED: Google Drive returned HTTP 403 at "
                    f"{exc.url} (insufficient OAuth scope or permissions)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: Google Drive returned HTTP 429 at {exc.url}"
                ) from exc
            raise ConnectorError(
                f"Google Drive API error: HTTP {status} at {exc.url}"
            ) from exc

    def _decode(self, response: Any, *, path: str, allow_empty: bool = False) -> dict[str, Any]:
        """Parse a Drive API response, mapping failures to distinct errors."""
        status = int(getattr(response, "status", 200) or 200)
        if status == 401:
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: Google Drive returned HTTP 401 at {path}"
            )
        if status == 403:
            raise PermissionDeniedError(
                f"PERMISSION_DENIED: Google Drive returned HTTP 403 at {path} "
                f"(insufficient OAuth scope or permissions)"
            )
        if status == 429:
            raise RateLimitError(f"RATE_LIMITED: Google Drive returned HTTP 429 at {path}")
        if status >= 400:
            raise ConnectorError(
                f"Google Drive API error: HTTP {status} at {path}: "
                f"{decode_error_payload(response.text)}"
            )
        if allow_empty and not response.text.strip():
            return {}
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from Google Drive at {path}: "
                "response body is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                f"invalid response from Google Drive at {path}: expected a JSON object"
            )
        return payload

    @staticmethod
    def _quote(value: str) -> str:
        from urllib.parse import quote

        return quote(str(value), safe="")
