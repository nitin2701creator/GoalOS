"""X/Twitter integration via the Twitter API v2.

``TwitterConnector`` talks to ``api.twitter.com/2`` over the shared HTTP
client using a Bearer token or OAuth 2.0 user token. It supports:

- Account lookup (authenticated user)
- Tweet creation (text, optionally with media)
- Tweet retrieval
- Tweet deletion
- User-level analytics (tweet metrics)

Honesty contract:

- Missing ``GOALOS_X_BEARER_TOKEN`` reports ``Not Configured``.
- HTTP 401 maps to :class:`AuthenticationError`.
- HTTP 403 maps to :class:`PermissionDeniedError`.
- HTTP 429 maps to :class:`RateLimitError`.
- Publishing requires ``PUBLISH_SOCIAL`` (dangerous, never implicit).
- The bearer token is never logged and never returned in results.
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

_TWITTER_API = "https://api.twitter.com/2"

# Capabilities that only read data
_READ_CAPABILITIES = frozenset({
    "twitter.health",
    "twitter.get_me",
    "twitter.get_tweet",
    "twitter.get_user_tweets",
    "twitter.get_tweet_metrics",
})

# Capabilities that publish/modify data
_WRITE_CAPABILITIES = frozenset({
    "twitter.create_tweet",
    "twitter.delete_tweet",
})


class TwitterConnector(IntegrationConnector):
    """X/Twitter connector for tweets and account management.

    Supports tweet publishing, retrieval, deletion, and basic analytics
    through the Twitter API v2.
    """

    required_env_vars: tuple[str, ...] = ("GOALOS_X_BEARER_TOKEN",)
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        cap: Permission.READ_SOCIAL if cap in _READ_CAPABILITIES else Permission.PUBLISH_SOCIAL
        for cap in (
            "twitter.health",
            "twitter.get_me",
            "twitter.get_tweet",
            "twitter.get_user_tweets",
            "twitter.get_tweet_metrics",
            "twitter.create_tweet",
            "twitter.delete_tweet",
        )
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        bearer_token: str | None = None,
    ) -> None:
        super().__init__(
            name="twitter",
            description="X/Twitter API v2 integration",
        )
        self.client = client or HttpClient()
        self.bearer_token = bearer_token or self._env("GOALOS_X_BEARER_TOKEN") or ""

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "twitter.health",
            "twitter.get_me",
            "twitter.get_tweet",
            "twitter.get_user_tweets",
            "twitter.get_tweet_metrics",
            "twitter.create_tweet",
            "twitter.delete_tweet",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        if not self.bearer_token:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                "missing environment configuration: GOALOS_X_BEARER_TOKEN",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "twitter.health":
            return self._health()
        if capability == "twitter.get_me":
            return self._get_me(params)
        if capability == "twitter.get_tweet":
            return self._get_tweet(params)
        if capability == "twitter.get_user_tweets":
            return self._get_user_tweets(params)
        if capability == "twitter.get_tweet_metrics":
            return self._get_tweet_metrics(params)
        if capability == "twitter.create_tweet":
            return self._create_tweet(params)
        if capability == "twitter.delete_tweet":
            return self._delete_tweet(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        from app.integrations.connector_health import ConnectorHealthStatus

        status, message = self._configuration_status()
        return {
            "integration": "twitter",
            "status": status.value,
            "configured": status is ConnectorHealthStatus.HEALTHY,
            "message": message,
        }

    def _get_me(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get the authenticated user's profile."""
        fields = params.get("fields") or "id,name,username,description,public_metrics,created_at"
        response = self._fetch("GET", f"{_TWITTER_API}/users/me", params={"fields": fields})
        payload = self._decode(response, path="users/me")
        user = payload.get("data", {})
        return {
            "user_id": user.get("id"),
            "name": user.get("name"),
            "username": user.get("username"),
            "description": user.get("description"),
            "metrics": user.get("public_metrics"),
            "created_at": user.get("created_at"),
        }

    def _get_tweet(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get a specific tweet."""
        tweet_id = params.get("tweet_id")
        if not tweet_id:
            raise ValueError("tweet_id is required for twitter.get_tweet")
        fields = params.get("fields") or (
            "id,text,created_at,public_metrics,author_id,lang,source"
        )
        response = self._fetch(
            "GET",
            f"{_TWITTER_API}/tweets/{tweet_id}",
            params={"fields": fields},
        )
        payload = self._decode(response, path=f"tweets/{tweet_id}")
        tweet = payload.get("data", {})
        metrics = tweet.get("public_metrics", {})
        return {
            "tweet_id": tweet.get("id"),
            "text": tweet.get("text"),
            "created_at": tweet.get("created_at"),
            "author_id": tweet.get("author_id"),
            "lang": tweet.get("lang"),
            "retweet_count": metrics.get("retweet_count", 0),
            "like_count": metrics.get("like_count", 0),
            "reply_count": metrics.get("reply_count", 0),
            "impression_count": metrics.get("impression_count", 0),
            "quote_count": metrics.get("quote_count", 0),
            "raw": tweet,
        }

    def _get_user_tweets(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get recent tweets from the authenticated user."""
        user_id = params.get("user_id")
        if not user_id:
            # Use /users/me/tweets for the authenticated user
            endpoint = f"{_TWITTER_API}/users/me/tweets"
        else:
            endpoint = f"{_TWITTER_API}/users/{user_id}/tweets"

        max_results = min(int(params.get("max_results") or 10), 100)
        query: dict[str, Any] = {
            "max_results": str(max_results),
            "fields": params.get("fields") or "id,text,created_at,public_metrics",
        }
        if params.get("since_id"):
            query["since_id"] = params["since_id"]
        if params.get("start_time"):
            query["start_time"] = params["start_time"]
        if params.get("end_time"):
            query["end_time"] = params["end_time"]

        response = self._fetch("GET", endpoint, params=query)
        payload = self._decode(response, path="user_tweets")
        tweets = payload.get("data", [])
        return {
            "total": len(tweets),
            "tweets": [
                {
                    "tweet_id": t.get("id"),
                    "text": t.get("text"),
                    "created_at": t.get("created_at"),
                    "metrics": t.get("public_metrics"),
                }
                for t in tweets
            ],
            "meta": payload.get("meta"),
        }

    def _get_tweet_metrics(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get aggregated metrics for tweets."""
        tweet_ids = params.get("tweet_ids") or []
        if not tweet_ids:
            # Get recent tweets with metrics
            result = self._get_user_tweets(params)
            total_metrics = {
                "retweet_count": 0,
                "like_count": 0,
                "reply_count": 0,
                "impression_count": 0,
                "quote_count": 0,
            }
            for tweet in result.get("tweets", []):
                metrics = tweet.get("metrics") or {}
                for key in total_metrics:
                    total_metrics[key] += metrics.get(key, 0)
            return {
                "source": "recent_tweets",
                "tweet_count": result["total"],
                "summary": total_metrics,
                "tweets": result["tweets"],
            }
        # Fetch specific tweets with metrics
        comma_ids = ",".join(str(tid) for tid in tweet_ids[:100])
        fields = "id,text,public_metrics,created_at"
        response = self._fetch(
            "GET",
            f"{_TWITTER_API}/tweets",
            params={"ids": comma_ids, "fields": fields},
        )
        payload = self._decode(response, path="tweets")
        tweets = payload.get("data", [])
        total_metrics = {
            "retweet_count": 0,
            "like_count": 0,
            "reply_count": 0,
            "impression_count": 0,
            "quote_count": 0,
        }
        for t in tweets:
            metrics = t.get("public_metrics") or {}
            for key in total_metrics:
                total_metrics[key] += metrics.get(key, 0)
        return {
            "source": "specified_tweets",
            "tweet_count": len(tweets),
            "summary": total_metrics,
            "tweets": [
                {
                    "tweet_id": t.get("id"),
                    "text": t.get("text"),
                    "metrics": t.get("public_metrics"),
                }
                for t in tweets
            ],
        }

    def _create_tweet(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new tweet."""
        text = params.get("text") or params.get("content")
        if not text:
            raise ValueError("text is required for twitter.create_tweet")
        body: dict[str, Any] = {"text": str(text)}
        if params.get("reply_to"):
            body["reply"] = {"in_reply_to_tweet_id": str(params["reply_to"])}
        if params.get("quote_tweet_id"):
            body["quote_tweet_id"] = str(params["quote_tweet_id"])

        response = self._fetch(
            "POST",
            f"{_TWITTER_API}/tweets",
            headers={"Content-Type": "application/json"},
            body=json.dumps(body).encode(),
        )
        payload = self._decode(response, path="tweets")
        tweet = payload.get("data", {})
        return {
            "created": True,
            "tweet_id": tweet.get("id"),
            "text": tweet.get("text"),
            "platform_url": f"https://x.com/i/status/{tweet.get('id')}",
        }

    def _delete_tweet(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete a tweet."""
        tweet_id = params.get("tweet_id")
        if not tweet_id:
            raise ValueError("tweet_id is required for twitter.delete_tweet")
        response = self._fetch(
            "DELETE",
            f"{_TWITTER_API}/tweets/{tweet_id}",
        )
        payload = self._decode(response, path=f"tweets/{tweet_id}")
        return {
            "deleted": True,
            "tweet_id": tweet_id,
            "success": payload.get("data", {}).get("deleted", False),
        }

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            **(extra_headers or {}),
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
        request_headers = self._headers(headers)
        try:
            return self.client.fetch(
                url, method=method, headers=request_headers, body=body, params=params
            )
        except HttpStatusError as exc:
            status = int(exc.status)
            if status == 401:
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: X/Twitter returned HTTP 401 at {exc.url} "
                    "(bearer token invalid or expired)"
                ) from exc
            if status == 403:
                raise PermissionDeniedError(
                    f"PERMISSION_DENIED: X/Twitter returned HTTP 403 at {exc.url} "
                    "(insufficient token scopes or permissions)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: X/Twitter returned HTTP 429 at {exc.url}"
                ) from exc
            raise ConnectorError(
                f"X/Twitter API error: HTTP {status} at {exc.url}"
            ) from exc

    def _decode(
        self, response: Any, *, path: str, allow_empty: bool = False
    ) -> dict[str, Any]:
        """Parse a Twitter API response, mapping failures to distinct errors."""
        status = int(getattr(response, "status", 200) or 200)
        if status == 401:
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: X/Twitter returned HTTP 401 at {path}"
            )
        if status == 403:
            raise PermissionDeniedError(
                f"PERMISSION_DENIED: X/Twitter returned HTTP 403 at {path}"
            )
        if status == 429:
            raise RateLimitError(f"RATE_LIMITED: X/Twitter returned HTTP 429 at {path}")
        if status >= 400:
            try:
                error_body = json.loads(response.text)
                errors = error_body.get("errors", [])
                error_msg = errors[0].get("message", response.text[:300]) if errors else response.text[:300]
            except Exception:
                error_msg = response.text[:300]
            raise ConnectorError(
                f"X/Twitter API error: HTTP {status} at {path}: {error_msg}"
            )
        if allow_empty and not response.text.strip():
            return {}
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from X/Twitter at {path}: response body is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                f"invalid response from X/Twitter at {path}: expected a JSON object"
            )
        # Check for Twitter-style errors in 200 response
        if "errors" in payload and isinstance(payload["errors"], list):
            for error in payload["errors"]:
                if isinstance(error, dict):
                    error_type = error.get("type", "")
                    if "unauthorized" in error_type.lower():
                        raise AuthenticationError(
                            f"AUTHENTICATION_FAILED: X/Twitter token error: {error.get('message', '')}"
                        )
        return payload
