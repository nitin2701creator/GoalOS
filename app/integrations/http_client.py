"""Shared HTTP transport for GoalOS external integrations.

A single real HTTP client is used by every external connector so timeouts,
redirects, status handling, response-size limits, and logging behave
consistently and can be tested with an injected opener. The client is
stdlib-only (``urllib``) so GoalOS runs on the KVM without extra
dependencies.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

#: Default cap on a downloaded response body (2 MiB).
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
#: Default per-request timeout in seconds.
DEFAULT_TIMEOUT = 15.0

Opener = Callable[..., Any]


class HttpError(Exception):
    """Base error for HTTP transport failures."""


class HttpConnectionError(HttpError):
    """Raised when the network or the remote server is unreachable."""


class HttpTimeoutError(HttpError):
    """Raised when a request exceeds its configured timeout."""


class HttpStatusError(HttpError):
    """Raised when the remote server returns a non-success status.

    Attributes:
        status: The HTTP status code returned by the server.
        url: The URL that produced the error.
    """

    def __init__(self, status: int, url: str, message: str = "") -> None:
        super().__init__(message or f"HTTP {status} for {url}")
        self.status = status
        self.url = url


class HttpResponseTooLargeError(HttpError):
    """Raised when a response body exceeds the configured limit."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """A normalized HTTP response.

    Attributes:
        status: HTTP status code.
        url: Final URL after redirects.
        headers: Response headers (lower-cased keys).
        body: Decoded response bytes.
        content_type: Response Content-Type header value.
    """

    status: int
    url: str
    headers: dict[str, str]
    body: bytes
    content_type: str | None

    @property
    def text(self) -> str:
        """Return the body decoded as UTF-8 with replacement fallback."""
        return self.body.decode("utf-8", errors="replace")


class HttpClient:
    """Real HTTP client with bounded, structured behavior.

    Args:
        timeout: Per-request timeout in seconds.
        max_bytes: Maximum response body size in bytes.
        opener: Optional callable(request) -> file-like; defaults to
            ``urllib.request.urlopen`` resolved at call time so tests can
            patch the module attribute.
        user_agent: User-Agent header value.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        opener: Opener | None = None,
        user_agent: str = "GoalOS-Integrations/0.5",
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._opener = opener
        self.user_agent = user_agent

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: float | None = None,
        max_bytes: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> HttpResponse:
        """Perform one bounded HTTP request and return the response.

        Args:
            params: Optional query-string parameters merged into the URL.

        Raises:
            HttpTimeoutError: If the request exceeds the timeout.
            HttpConnectionError: If the remote host is unreachable.
            HttpStatusError: If the server returns a non-2xx status.
            HttpResponseTooLargeError: If the body exceeds the limit.
        """
        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params)}"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HttpConnectionError(f"invalid URL: {url}")

        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "*/*",
                **(headers or {}),
            },
        )
        limit = max_bytes or self.max_bytes
        timeout_s = timeout or self.timeout

        opener = self._opener or urlopen
        try:
            with opener(request, timeout=timeout_s) as response:
                status = int(getattr(response, "status", 200) or 200)
                final_url = response.geturl()
                raw_headers = {
                    key.lower(): value for key, value in response.headers.items()
                }
                content_type = raw_headers.get("content-type")
                payload = self._read_bounded(response, limit)
        except HTTPError as exc:
            status = int(exc.code)
            final_url = getattr(exc, "url", url) or url
            raw_headers = {key.lower(): value for key, value in exc.headers.items()} if exc.headers else {}
            content_type = raw_headers.get("content-type")
            try:
                payload = self._read_bounded(exc, limit)
            except HttpResponseTooLargeError:
                payload = b""
            if status < 400 or status >= 500:
                logger.warning("HTTP %s from %s", status, final_url)
                raise HttpStatusError(status, final_url)
            # 4xx responses are returned as-is so callers can handle them.
            return HttpResponse(status, final_url, raw_headers, payload, content_type)
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
                logger.warning("HTTP timeout for %s", url)
                raise HttpTimeoutError(f"request timed out after {timeout_s}s: {url}") from exc
            logger.warning("HTTP connection error for %s: %s", url, reason)
            raise HttpConnectionError(f"cannot reach {url}: {reason}") from exc
        except TimeoutError as exc:
            logger.warning("HTTP timeout for %s", url)
            raise HttpTimeoutError(f"request timed out after {timeout_s}s: {url}") from exc
        except OSError as exc:
            logger.warning("HTTP transport error for %s: %s", url, exc)
            raise HttpConnectionError(f"cannot reach {url}: {exc}") from exc

        if status >= 400:
            logger.warning("HTTP %s from %s", status, final_url)
            raise HttpStatusError(status, final_url)
        return HttpResponse(status, final_url, raw_headers, payload, content_type)

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        """Convenience GET wrapper around :meth:`fetch`."""
        return self.fetch(url, **kwargs)

    def _read_bounded(self, response: Any, limit: int) -> bytes:
        """Read a response body while enforcing the byte cap."""
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(min(limit - total + 1, 64 * 1024))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise HttpResponseTooLargeError(
                    f"response body exceeds {limit} byte limit"
                )
            chunks.append(chunk)
        return b"".join(chunks)
