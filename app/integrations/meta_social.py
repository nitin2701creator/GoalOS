"""Meta/Facebook/Instagram social media connector for GoalOS.

``MetaSocialConnector`` talks to the Facebook Graph API (``graph.facebook.com``)
over the shared HTTP client. It supports:

- Page discovery (list Facebook Pages the token has access to)
- Instagram Business account discovery (associated with Pages)
- Page publishing (text, image, link posts)
- Post retrieval and deletion
- Page/Post analytics (engagement metrics)

Authentication uses either:
1. A Page Access Token from Facebook OAuth (recommended for publishing)
2. A User Access Token with ``pages_show_list``, ``pages_read_engagement``,
   ``pages_manage_posts`` scopes

Honesty contract:
- Missing ``GOALOS_META_PAGE_ACCESS_TOKEN`` reports ``Not Configured``.
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

_GRAPH_API = "https://graph.facebook.com/v21.0"

# Capabilities that only read data
_READ_CAPABILITIES = frozenset({
    "meta_social.health",
    "meta_social.list_pages",
    "meta_social.list_instagram_accounts",
    "meta_social.get_page_info",
    "meta_social.get_post",
    "meta_social.get_page_insights",
    "meta_social.get_post_insights",
})

# Capabilities that publish/modify data
_WRITE_CAPABILITIES = frozenset({
    "meta_social.publish_post",
    "meta_social.delete_post",
})


class MetaSocialConnector(IntegrationConnector):
    """Meta/Facebook/Instagram social media connector.

    Supports page discovery, content publishing, post retrieval, and
    analytics through the Facebook Graph API.
    """

    required_env_vars: tuple[str, ...] = ("GOALOS_META_PAGE_ACCESS_TOKEN",)
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        cap: Permission.READ_SOCIAL if cap in _READ_CAPABILITIES else Permission.PUBLISH_SOCIAL
        for cap in (
            "meta_social.health",
            "meta_social.list_pages",
            "meta_social.list_instagram_accounts",
            "meta_social.get_page_info",
            "meta_social.get_post",
            "meta_social.publish_post",
            "meta_social.delete_post",
            "meta_social.get_page_insights",
            "meta_social.get_post_insights",
        )
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        page_access_token: str | None = None,
    ) -> None:
        super().__init__(
            name="meta_social",
            description="Meta/Facebook/Instagram social media connector",
        )
        self.client = client or HttpClient()
        self.page_access_token = (
            page_access_token or self._env("GOALOS_META_PAGE_ACCESS_TOKEN") or ""
        )

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "meta_social.health",
            "meta_social.list_pages",
            "meta_social.list_instagram_accounts",
            "meta_social.get_page_info",
            "meta_social.get_post",
            "meta_social.publish_post",
            "meta_social.delete_post",
            "meta_social.get_page_insights",
            "meta_social.get_post_insights",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        if not self.page_access_token:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                "missing environment configuration: GOALOS_META_PAGE_ACCESS_TOKEN",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "meta_social.health":
            return self._health()
        if capability == "meta_social.list_pages":
            return self._list_pages(params)
        if capability == "meta_social.list_instagram_accounts":
            return self._list_instagram_accounts(params)
        if capability == "meta_social.get_page_info":
            return self._get_page_info(params)
        if capability == "meta_social.get_post":
            return self._get_post(params)
        if capability == "meta_social.publish_post":
            return self._publish_post(params)
        if capability == "meta_social.delete_post":
            return self._delete_post(params)
        if capability == "meta_social.get_page_insights":
            return self._get_page_insights(params)
        if capability == "meta_social.get_post_insights":
            return self._get_post_insights(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        from app.integrations.connector_health import ConnectorHealthStatus

        status, message = self._configuration_status()
        return {
            "integration": "meta_social",
            "status": status.value,
            "configured": status is ConnectorHealthStatus.HEALTHY,
            "message": message,
        }

    def _list_pages(self, params: dict[str, Any]) -> dict[str, Any]:
        """List Facebook Pages accessible with the current token."""
        fields = params.get("fields") or "id,name,category,fan_count,access_token"
        response = self._fetch("GET", f"{_GRAPH_API}/me/accounts", params={"fields": fields})
        payload = self._decode(response, path="me/accounts")
        items = payload.get("data") or []
        return {
            "total": len(items),
            "pages": [
                {
                    "page_id": item.get("id"),
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "fan_count": item.get("fan_count"),
                    "has_instagram": bool(item.get("instagram_business_account")),
                }
                for item in items
                if isinstance(item, dict)
            ],
            "paging": payload.get("paging"),
        }

    def _list_instagram_accounts(self, params: dict[str, Any]) -> dict[str, Any]:
        """List Instagram Business accounts associated with a Facebook Page."""
        page_id = params.get("page_id")
        if not page_id:
            raise ValueError("page_id is required for meta_social.list_instagram_accounts")
        fields = params.get("fields") or "id,username,name,profile_picture_url,followers_count"
        response = self._fetch(
            "GET",
            f"{_GRAPH_API}/{page_id}",
            params={"fields": f"instagram_business_account{{{fields}}}"},
        )
        payload = self._decode(response, path=f"pages/{page_id}")
        ig_account = payload.get("instagram_business_account")
        if not ig_account:
            return {
                "page_id": page_id,
                "instagram_account": None,
                "message": "No Instagram Business account is linked to this Page",
            }
        return {
            "page_id": page_id,
            "instagram_account": {
                "account_id": ig_account.get("id"),
                "username": ig_account.get("username"),
                "name": ig_account.get("name"),
                "profile_picture_url": ig_account.get("profile_picture_url"),
                "followers_count": ig_account.get("followers_count"),
            },
        }

    def _get_page_info(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get detailed information about a Facebook Page."""
        page_id = params.get("page_id")
        if not page_id:
            raise ValueError("page_id is required for meta_social.get_page_info")
        fields = params.get("fields") or (
            "id,name,about,category,fan_count,followers_count,link,"
            "picture,website,location,description"
        )
        response = self._fetch("GET", f"{_GRAPH_API}/{page_id}", params={"fields": fields})
        return {"page": self._decode(response, path=f"pages/{page_id}")}

    def _get_post(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get a specific post from a Facebook Page."""
        post_id = params.get("post_id")
        if not post_id:
            raise ValueError("post_id is required for meta_social.get_post")
        fields = params.get("fields") or (
            "id,message,created_time,type,full_picture,permalink_url,"
            "shares,likes.summary(true),comments.summary(true)"
        )
        response = self._fetch("GET", f"{_GRAPH_API}/{post_id}", params={"fields": fields})
        payload = self._decode(response, path=f"posts/{post_id}")
        return {
            "post_id": payload.get("id"),
            "message": payload.get("message"),
            "created_time": payload.get("created_time"),
            "type": payload.get("type"),
            "permalink_url": payload.get("permalink_url"),
            "full_picture": payload.get("full_picture"),
            "shares": (payload.get("shares") or {}).get("count", 0),
            "likes": (payload.get("likes") or {}).get("summary", {}).get("total_count", 0),
            "comments": (payload.get("comments") or {}).get("summary", {}).get("total_count", 0),
            "raw": payload,
        }

    def _publish_post(self, params: dict[str, Any]) -> dict[str, Any]:
        """Publish a post to a Facebook Page."""
        page_id = params.get("page_id")
        if not page_id:
            raise ValueError("page_id is required for meta_social.publish_post")
        message = params.get("message") or params.get("content")
        if not message:
            raise ValueError("message is required for meta_social.publish_post")

        body: dict[str, Any] = {"message": str(message)}
        if params.get("link"):
            body["link"] = params["link"]
        if params.get("picture"):
            body["picture"] = params["picture"]
        if params.get("name"):
            body["name"] = params["name"]
        if params.get("description"):
            body["description"] = params["description"]

        # Use page-specific access token if provided
        access_token = params.get("access_token") or self.page_access_token

        response = self._fetch(
            "POST",
            f"{_GRAPH_API}/{page_id}/feed",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=self._url_encode(body).encode(),
            extra_token=access_token,
        )
        payload = self._decode(response, path=f"pages/{page_id}/feed")
        post_id = payload.get("id", "")
        return {
            "created": True,
            "page_id": page_id,
            "post_id": post_id,
            "platform_url": f"https://facebook.com/{post_id}",
            "data": payload,
        }

    def _delete_post(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a post from a Facebook Page."""
        post_id = params.get("post_id")
        if not post_id:
            raise ValueError("post_id is required for meta_social.delete_post")
        response = self._fetch("DELETE", f"{_GRAPH_API}/{post_id}")
        payload = self._decode(response, path=f"posts/{post_id}", allow_empty=True)
        return {"deleted": True, "post_id": post_id, "success": payload.get("success", True)}

    def _get_page_insights(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get engagement insights for a Facebook Page."""
        page_id = params.get("page_id")
        if not page_id:
            raise ValueError("page_id is required for meta_social.get_page_insights")
        metrics = params.get("metrics") or (
            "page_impressions,page_engaged_users,page_post_engagements,"
            "page_fan_adds,page_fan_removes,page_views_total"
        )
        period = params.get("period") or "day"
        since = params.get("since")
        until = params.get("until")

        query: dict[str, Any] = {"metric": metrics, "period": period}
        if since:
            query["since"] = since
        if until:
            query["until"] = until

        response = self._fetch(
            "GET", f"{_GRAPH_API}/{page_id}/insights", params=query
        )
        payload = self._decode(response, path=f"pages/{page_id}/insights")
        data = payload.get("data") or []

        # Normalize insights into a flat summary
        summary: dict[str, Any] = {}
        for metric in data:
            if not isinstance(metric, dict):
                continue
            name = metric.get("name", "")
            values = metric.get("values") or []
            if values and isinstance(values, list):
                # Sum values across the period
                total = 0
                for v in values:
                    if isinstance(v, dict):
                        total += float(v.get("value", 0))
                summary[name] = total
            else:
                summary[name] = 0

        return {
            "page_id": page_id,
            "period": period,
            "metrics": data,
            "summary": summary,
        }

    def _get_post_insights(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get engagement insights for a specific post."""
        post_id = params.get("post_id")
        if not post_id:
            raise ValueError("post_id is required for meta_social.get_post_insights")
        metrics = params.get("metrics") or (
            "post_impressions,post_engagements,post_reactions_by_type_total,"
            "post_video_views,post_clicks"
        )
        response = self._fetch(
            "GET", f"{_GRAPH_API}/{post_id}/insights", params={"metric": metrics}
        )
        payload = self._decode(response, path=f"posts/{post_id}/insights")
        data = payload.get("data") or []
        summary: dict[str, Any] = {}
        for metric in data:
            if not isinstance(metric, dict):
                continue
            name = metric.get("name", "")
            values = metric.get("values") or []
            if values and isinstance(values, list):
                summary[name] = values[0].get("value", 0) if values else 0
            else:
                summary[name] = 0
        return {
            "post_id": post_id,
            "metrics": data,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _headers(
        self, extra_token: str | None = None, extra_headers: dict[str, str] | None = None
    ) -> dict[str, str]:
        token = extra_token or self.page_access_token
        return {"Authorization": f"Bearer {token}", **(extra_headers or {})}

    def _fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        params: dict[str, Any] | None = None,
        extra_token: str | None = None,
    ) -> Any:
        """Issue one authenticated request with stable error mapping."""
        request_headers = self._headers(extra_token=extra_token)
        if headers:
            request_headers.update(headers)
        try:
            return self.client.fetch(
                url, method=method, headers=request_headers, body=body, params=params
            )
        except HttpStatusError as exc:
            status = int(exc.status)
            if status == 401:
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: Meta returned HTTP 401 at {exc.url} "
                    "(token invalid or expired)"
                ) from exc
            if status == 403:
                raise PermissionDeniedError(
                    f"PERMISSION_DENIED: Meta returned HTTP 403 at {exc.url} "
                    "(insufficient token scopes or permissions)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: Meta returned HTTP 429 at {exc.url}"
                ) from exc
            raise ConnectorError(
                f"Meta API error: HTTP {status} at {exc.url}"
            ) from exc

    def _decode(
        self, response: Any, *, path: str, allow_empty: bool = False
    ) -> dict[str, Any]:
        """Parse a Meta Graph API response, mapping failures to distinct errors."""
        status = int(getattr(response, "status", 200) or 200)
        if status == 401:
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: Meta returned HTTP 401 at {path}"
            )
        if status == 403:
            raise PermissionDeniedError(
                f"PERMISSION_DENIED: Meta returned HTTP 403 at {path}"
            )
        if status == 429:
            raise RateLimitError(f"RATE_LIMITED: Meta returned HTTP 429 at {path}")
        if status >= 400:
            try:
                error_body = json.loads(response.text)
                error = error_body.get("error", {})
                error_msg = error.get("message", response.text[:300])
            except Exception:
                error_msg = response.text[:300]
            raise ConnectorError(
                f"Meta API error: HTTP {status} at {path}: {error_msg}"
            )
        if allow_empty and not response.text.strip():
            return {}
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from Meta at {path}: response body is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                f"invalid response from Meta at {path}: expected a JSON object"
            )
        # Check for Meta-style error in 200 response
        if "error" in payload and isinstance(payload["error"], dict):
            error = payload["error"]
            error_code = error.get("code", 0)
            error_msg = error.get("message", "Unknown error")
            if error_code in (190, 102, 463):
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: Meta token error {error_code}: {error_msg}"
                )
            if error_code in (200, 299):
                raise PermissionDeniedError(
                    f"PERMISSION_DENIED: Meta permission error {error_code}: {error_msg}"
                )
            raise ConnectorError(
                f"Meta API error {error_code}: {error_msg}"
            )
        return payload

    @staticmethod
    def _url_encode(data: dict[str, Any]) -> str:
        """URL-encode a dict for form-encoded POST bodies."""
        from urllib.parse import urlencode

        return urlencode(data)
