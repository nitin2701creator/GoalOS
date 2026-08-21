"""Reddit integration via the Reddit API (oauth.reddit.com).

``RedditConnector`` talks to ``oauth.reddit.com`` over the shared HTTP
client using a Bearer token obtained through OAuth2 client credentials
or user authorization. It supports:

- Account info (authenticated user)
- Subreddit listing
- Post submission (link or text)
- Post retrieval
- Comment submission
- Post/comment voting is intentionally NOT supported (read-only for votes)

Honesty contract:

- Missing ``GOALOS_REDDIT_ACCESS_TOKEN`` reports ``Not Configured``.
- HTTP 401 maps to :class:`AuthenticationError`.
- HTTP 403 maps to :class:`PermissionDeniedError`.
- HTTP 429 maps to :class:`RateLimitError`.
- Publishing requires ``PUBLISH_SOCIAL`` (dangerous, never implicit).
- The access token is never logged and never returned in results.
"""

from __future__ import annotations

import json
import logging
from typing import Any, ClassVar

from app.agents.permissions import Permission
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient, HttpStatusError
from app.integrations.integration_connector import IntegrationConnector

logger = logging.getLogger(__name__)

_REDDIT_API = "https://oauth.reddit.com"
_USER_AGENT = "GoalOS/1.0 (Social Integration)"

# Read-only capabilities
_READ_CAPABILITIES = frozenset({
    "reddit.health",
    "reddit.get_me",
    "reddit.list_subreddits",
    "reddit.get_post",
    "reddit.get_subreddit",
})

# Write capabilities
_WRITE_CAPABILITIES = frozenset({
    "reddit.submit_post",
    "reddit.submit_comment",
})


class RedditConnector(IntegrationConnector):
    """Reddit connector for subreddits, posts, and comments.

    Supports posting text/link submissions, commenting, and reading
    subreddit and post information through the Reddit API.
    """

    required_env_vars: tuple[str, ...] = ("GOALOS_REDDIT_ACCESS_TOKEN",)
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        cap: Permission.READ_SOCIAL if cap in _READ_CAPABILITIES else Permission.PUBLISH_SOCIAL
        for cap in (
            "reddit.health",
            "reddit.get_me",
            "reddit.list_subreddits",
            "reddit.get_post",
            "reddit.get_subreddit",
            "reddit.submit_post",
            "reddit.submit_comment",
        )
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        access_token: str | None = None,
    ) -> None:
        super().__init__(
            name="reddit",
            description="Reddit API integration (subreddits, posts, comments)",
        )
        self.client = client or HttpClient()
        self.access_token = access_token or self._env("GOALOS_REDDIT_ACCESS_TOKEN") or ""

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "reddit.health",
            "reddit.get_me",
            "reddit.list_subreddits",
            "reddit.get_post",
            "reddit.get_subreddit",
            "reddit.submit_post",
            "reddit.submit_comment",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        if not self.access_token:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                "missing environment configuration: GOALOS_REDDIT_ACCESS_TOKEN",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "reddit.health":
            return self._health()
        if capability == "reddit.get_me":
            return self._get_me(params)
        if capability == "reddit.list_subreddits":
            return self._list_subreddits(params)
        if capability == "reddit.get_post":
            return self._get_post(params)
        if capability == "reddit.get_subreddit":
            return self._get_subreddit(params)
        if capability == "reddit.submit_post":
            return self._submit_post(params)
        if capability == "reddit.submit_comment":
            return self._submit_comment(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        from app.integrations.connector_health import ConnectorHealthStatus

        status, message = self._configuration_status()
        return {
            "integration": "reddit",
            "status": status.value,
            "configured": status is ConnectorHealthStatus.HEALTHY,
            "message": message,
        }

    def _get_me(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get the authenticated user's Reddit profile."""
        response = self._fetch("GET", "/api/v1/me")
        payload = self._decode(response, path="me")
        return {
            "user_id": payload.get("id"),
            "name": payload.get("name"),
            "link_karma": payload.get("link_karma"),
            "comment_karma": payload.get("comment_karma"),
            "created_utc": payload.get("created_utc"),
            "verified": payload.get("verified"),
            "has_verified_email": payload.get("has_verified_email"),
        }

    def _list_subreddits(self, params: dict[str, Any]) -> dict[str, Any]:
        """List subreddits the user is subscribed to."""
        limit = min(int(params.get("limit") or 25), 100)
        after = params.get("after") or ""
        response = self._fetch(
            "GET",
            "/subreddits/mine/subscriber",
            params={"limit": str(limit), "after": after},
        )
        payload = self._decode(response, path="subreddits/mine")
        children = payload.get("data", {}).get("children", [])
        subreddits = []
        for child in children:
            data = child.get("data", {})
            subreddits.append({
                "subreddit_id": data.get("subreddit_id") or data.get("name"),
                "display_name": data.get("display_name") or data.get("display_name_prefixed"),
                "title": data.get("title"),
                "subscribers": data.get("subscribers"),
                "description": data.get("public_description"),
                "url": f"https://reddit.com{data.get('url', '')}",
            })
        return {
            "total": len(subreddits),
            "subreddits": subreddits,
            "after": payload.get("data", {}).get("after"),
        }

    def _get_post(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get a specific Reddit post."""
        post_id = params.get("post_id") or params.get("submission_id")
        if not post_id:
            raise ValueError("post_id is required for reddit.get_post")
        # Use /api/info for single post lookup
        response = self._fetch(
            "GET",
            "/api/info",
            params={"id": f"t3_{post_id}"},
        )
        payload = self._decode(response, path="info")
        children = payload.get("data", {}).get("children", [])
        if not children:
            raise ConnectorError(f"Reddit post not found: {post_id}")
        post_data = children[0].get("data", {})
        return {
            "post_id": post_data.get("id"),
            "title": post_data.get("title"),
            "selftext": post_data.get("selftext"),
            "url": post_data.get("url"),
            "subreddit": post_data.get("subreddit"),
            "author": post_data.get("author"),
            "score": post_data.get("score"),
            "num_comments": post_data.get("num_comments"),
            "created_utc": post_data.get("created_utc"),
            "permalink": f"https://reddit.com{post_data.get('permalink', '')}",
            "is_self": post_data.get("is_self"),
        }

    def _get_subreddit(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get information about a subreddit."""
        subreddit = params.get("subreddit") or params.get("subreddit_name")
        if not subreddit:
            raise ValueError("subreddit is required for reddit.get_subreddit")
        response = self._fetch("GET", f"/r/{subreddit}/about")
        payload = self._decode(response, path=f"r/{subreddit}/about")
        data = payload.get("data", {})
        return {
            "subreddit_id": data.get("subreddit_id") or data.get("name"),
            "display_name": data.get("display_name"),
            "title": data.get("title"),
            "subscribers": data.get("subscribers"),
            "active_user_count": data.get("active_user_count"),
            "description": data.get("public_description"),
            "created_utc": data.get("created_utc"),
            "url": f"https://reddit.com/r/{data.get('display_name', subreddit)}",
        }

    def _submit_post(self, params: dict[str, Any]) -> dict[str, Any]:
        """Submit a post to a subreddit."""
        subreddit = params.get("subreddit")
        if not subreddit:
            raise ValueError("subreddit is required for reddit.submit_post")
        title = params.get("title")
        if not title:
            raise ValueError("title is required for reddit.submit_post")

        body: dict[str, Any] = {
            "sr": str(subreddit),
            "title": str(title),
            "kind": params.get("kind") or "self",
        }
        if body["kind"] == "self":
            body["text"] = params.get("text") or params.get("content") or ""
        elif body["kind"] == "link":
            body["url"] = params.get("url") or ""

        response = self._fetch(
            "POST",
            "/api/submit",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=self._url_encode(body).encode(),
        )
        payload = self._decode(response, path="submit")
        # Reddit returns {"jquery": [[...], ...]} format
        success = False
        post_id = None
        for item in payload.get("jquery", []):
            if isinstance(item, list) and len(item) >= 2:
                if item[0] == "error":
                    error_msg = item[1] if len(item) > 1 else "Unknown error"
                    raise ConnectorError(f"Reddit submission error: {error_msg}")
                if item[0] == "success":
                    success = True
                    # Extract post URL from the success data
                    if len(item) > 3 and isinstance(item[3], dict):
                        post_id = item[3].get("id")
                        post_url = item[3].get("url")
                    elif len(item) > 2 and isinstance(item[2], dict):
                        post_url = item[2].get("url")

        return {
            "created": success,
            "subreddit": subreddit,
            "title": title,
            "post_id": post_id,
            "permalink": f"https://reddit.com/r/{subreddit}/comments/{post_id}" if post_id else None,
        }

    def _submit_comment(self, params: dict[str, Any]) -> dict[str, Any]:
        """Submit a comment on a Reddit post."""
        post_id = params.get("post_id") or params.get("parent_id")
        if not post_id:
            raise ValueError("post_id is required for reddit.submit_comment")
        text = params.get("text") or params.get("content")
        if not text:
            raise ValueError("text is required for reddit.submit_comment")

        body = {
            "parent": f"t3_{post_id}",
            "text": str(text),
        }
        response = self._fetch(
            "POST",
            "/api/comment",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=self._url_encode(body).encode(),
        )
        payload = self._decode(response, path="comment")
        success = False
        comment_id = None
        for item in payload.get("jquery", []):
            if isinstance(item, list) and len(item) >= 2:
                if item[0] == "error":
                    error_msg = item[1] if len(item) > 1 else "Unknown error"
                    raise ConnectorError(f"Reddit comment error: {error_msg}")
                if item[0] == "success":
                    success = True
                    if len(item) > 2 and isinstance(item[2], dict):
                        comment_id = item[2].get("id")

        return {
            "created": success,
            "post_id": post_id,
            "comment_id": comment_id,
        }

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": _USER_AGENT,
            **(extra_headers or {}),
        }

    def _fetch(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue one authenticated request with stable error mapping."""
        url = f"{_REDDIT_API}{path}"
        request_headers = self._headers(headers)
        try:
            return self.client.fetch(
                url, method=method, headers=request_headers, body=body, params=params
            )
        except HttpStatusError as exc:
            status = int(exc.status)
            if status == 401:
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: Reddit returned HTTP 401 at {exc.url} "
                    "(access token invalid or expired)"
                ) from exc
            if status == 403:
                raise PermissionDeniedError(
                    f"PERMISSION_DENIED: Reddit returned HTTP 403 at {exc.url} "
                    "(insufficient token scopes or permissions)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: Reddit returned HTTP 429 at {exc.url}"
                ) from exc
            raise ConnectorError(
                f"Reddit API error: HTTP {status} at {exc.url}"
            ) from exc

    def _decode(
        self, response: Any, *, path: str, allow_empty: bool = False
    ) -> dict[str, Any]:
        """Parse a Reddit API response, mapping failures to distinct errors."""
        status = int(getattr(response, "status", 200) or 200)
        if status == 401:
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: Reddit returned HTTP 401 at {path}"
            )
        if status == 403:
            raise PermissionDeniedError(
                f"PERMISSION_DENIED: Reddit returned HTTP 403 at {path}"
            )
        if status == 429:
            raise RateLimitError(f"RATE_LIMITED: Reddit returned HTTP 429 at {path}")
        if status >= 400:
            try:
                error_body = json.loads(response.text)
                error_msg = error_body.get("message", response.text[:300])
            except Exception:
                error_msg = response.text[:300]
            raise ConnectorError(
                f"Reddit API error: HTTP {status} at {path}: {error_msg}"
            )
        if allow_empty and not response.text.strip():
            return {}
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from Reddit at {path}: response body is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                f"invalid response from Reddit at {path}: expected a JSON object"
            )
        return payload

    @staticmethod
    def _url_encode(data: dict[str, Any]) -> str:
        """URL-encode a dict for form-encoded POST bodies."""
        from urllib.parse import urlencode
        return urlencode(data)
