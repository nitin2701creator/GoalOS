"""Tests for the Google Drive connector.

Covers: provider-not-configured honesty, search, metadata retrieval,
downloads (bounded content, honest truncation), uploads (text and base64),
folder creation, moves, deletes, folder listing, distinct authentication
failure, permission denial, rate limiting, and malformed responses. Never
touches the real Google Drive API.
"""

from __future__ import annotations

import base64

import pytest

from app.agents.permissions import Permission
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.exceptions import (
    AuthenticationError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.google_drive import GoogleDriveConnector
from app.integrations.http_client import HttpClient
from tests.google_helpers import FakeGoogleToken, GoogleFakeOpener
from tests.integration_helpers import FakeResponse

FILE_1 = {"id": "file-1", "name": "quotation.pdf", "mimeType": "application/pdf", "size": "1024"}
FILES_LIST = {"files": [FILE_1]}
FOLDER = {"id": "folder-1", "name": "Suppliers", "mimeType": "application/vnd.google-apps.folder"}


def _connector(opener=None, *, token: FakeGoogleToken | None = None) -> GoogleDriveConnector:
    return GoogleDriveConnector(
        client=HttpClient(opener=opener),
        token_provider=token or FakeGoogleToken(),
    )


def test_drive_reports_not_configured_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    connector = GoogleDriveConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
    assert not connector.is_configured
    available, reason = connector.capability_available("drive.search")
    assert not available
    assert "GOOGLE_CLIENT_ID" in reason


def test_drive_search_files() -> None:
    opener = GoogleFakeOpener({("GET", "/drive/v3/files"): FILES_LIST})
    connector = _connector(opener)

    result = connector.execute(
        "drive.search", {"query": "name contains 'quotation'", "page_size": 10},
        permissions={Permission.READ_DRIVE},
    )
    assert result["items"][0]["name"] == "quotation.pdf"
    method, url = opener.calls[0]
    assert method == "GET"
    assert "q=name+contains" in url


def test_drive_get_file() -> None:
    opener = GoogleFakeOpener({("GET", "/drive/v3/files/file-1"): FILE_1})
    connector = _connector(opener)

    result = connector.execute("drive.get_file", {"file_id": "file-1"}, permissions={Permission.READ_DRIVE})
    assert result["file"]["name"] == "quotation.pdf"


def test_drive_download_file_returns_bounded_content() -> None:
    content = b"%PDF-1.4 fake pdf bytes"
    opener = GoogleFakeOpener(
        {
            ("GET", "/drive/v3/files/file-1"): FILE_1,
            ("GET", "alt=media"): content,
        }
    )
    connector = _connector(opener)

    result = connector.execute(
        "drive.download_file", {"file_id": "file-1", "max_bytes": 1024 * 1024},
        permissions={Permission.READ_DRIVE},
    )
    assert result["size_bytes"] == len(content)
    assert base64.b64decode(result["content_base64"]) == content
    assert result["truncated"] is False


def test_drive_download_truncation_is_honest() -> None:
    content = b"x" * 5000
    opener = GoogleFakeOpener(
        {
            ("GET", "/drive/v3/files/file-1"): {**FILE_1, "size": str(len(content))},
            ("GET", "alt=media"): content,
        }
    )
    connector = _connector(opener)

    result = connector.execute(
        "drive.download_file", {"file_id": "file-1", "max_bytes": 100},
        permissions={Permission.READ_DRIVE},
    )
    assert result["size_bytes"] == 100
    assert result["truncated"] is True


def test_drive_upload_file_text_content() -> None:
    opener = GoogleFakeOpener({("POST", "/upload/drive/v3/files"): FILE_1})
    connector = _connector(opener)

    result = connector.execute(
        "drive.upload_file",
        {"name": "quotation.pdf", "content": "hello", "content_type": "text/plain"},
        permissions={Permission.READ_DRIVE, Permission.WRITE_DRIVE},
    )
    assert result["uploaded"] is True
    method, url = opener.calls[0]
    assert method == "POST"
    assert "uploadType=media" in url


def test_drive_upload_file_base64_content() -> None:
    opener = GoogleFakeOpener({("POST", "/upload/drive/v3/files"): FILE_1})
    connector = _connector(opener)

    result = connector.execute(
        "drive.upload_file",
        {"name": "quote.bin", "content_base64": base64.b64encode(b"\x00\x01\x02").decode()},
        permissions={Permission.READ_DRIVE, Permission.WRITE_DRIVE},
    )
    assert result["uploaded"] is True


def test_drive_create_folder() -> None:
    opener = GoogleFakeOpener({("POST", "/drive/v3/files"): FOLDER})
    connector = _connector(opener)

    result = connector.execute(
        "drive.create_folder",
        {"name": "Suppliers", "parents": ["parent-1"]},
        permissions={Permission.READ_DRIVE, Permission.WRITE_DRIVE},
    )
    assert result["folder"]["mime_type"] == "application/vnd.google-apps.folder"


def test_drive_move_file() -> None:
    opener = GoogleFakeOpener({("PATCH", "/drive/v3/files/file-1"): {**FILE_1, "parents": ["new-parent"]}})
    connector = _connector(opener)

    result = connector.execute(
        "drive.move_file",
        {"file_id": "file-1", "add_parents": ["new-parent"], "remove_parents": ["old-parent"]},
        permissions={Permission.READ_DRIVE, Permission.WRITE_DRIVE},
    )
    assert result["moved"] is True
    method, url = opener.calls[0]
    assert method == "PATCH"
    assert "addParents=new-parent" in url and "removeParents=old-parent" in url


def test_drive_delete_file() -> None:
    opener = GoogleFakeOpener({("DELETE", "/drive/v3/files/file-1"): (204, None)})
    connector = _connector(opener)

    result = connector.execute(
        "drive.delete_file", {"file_id": "file-1"},
        permissions={Permission.READ_DRIVE, Permission.WRITE_DRIVE},
    )
    assert result["deleted"] is True


def test_drive_write_requires_write_permission() -> None:
    connector = _connector(GoogleFakeOpener())
    with pytest.raises(PermissionDeniedError, match="WRITE_DRIVE"):
        connector.execute(
            "drive.upload_file", {"name": "x.txt", "content": "hi"},
            permissions={Permission.READ_DRIVE},
        )


def test_drive_list_folder() -> None:
    opener = GoogleFakeOpener({("GET", "/drive/v3/files"): FILES_LIST})
    connector = _connector(opener)

    result = connector.execute(
        "drive.list_folder", {"folder_id": "folder-1"},
        permissions={Permission.READ_DRIVE},
    )
    assert result["folder_id"] == "folder-1"
    assert result["items"][0]["id"] == "file-1"
    _, url = opener.calls[0]
    assert "folder-1%27+in+parents" in url


def test_drive_auth_failure_is_distinct() -> None:
    opener = GoogleFakeOpener(default_status=401, default_payload={"error": "unauthorized"})
    connector = _connector(opener)
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        connector.execute("drive.search", {}, permissions={Permission.READ_DRIVE})


def test_drive_rate_limit_is_distinct() -> None:
    opener = GoogleFakeOpener(default_status=429, default_payload={"error": {"message": "rate limit"}})
    connector = _connector(opener)
    with pytest.raises(RateLimitError, match="RATE_LIMITED"):
        connector.execute("drive.search", {}, permissions={Permission.READ_DRIVE})


def test_drive_malformed_response_raises_structured_error() -> None:
    def garbage(request, timeout=None) -> FakeResponse:
        return FakeResponse(b"<html>not json</html>", str(request.full_url), content_type="text/html")

    connector = _connector(garbage)
    with pytest.raises(ConnectorError, match="not valid JSON"):
        connector.execute("drive.search", {}, permissions={Permission.READ_DRIVE})


def test_drive_health_capability() -> None:
    connector = _connector(GoogleFakeOpener())
    result = connector.execute("drive.health", {}, permissions={Permission.READ_DRIVE})
    assert result["configured"] is True
    assert result["integration"] == "drive"
