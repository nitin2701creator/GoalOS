"""Social media API endpoints for GoalOS.

Provides provider discovery, connected account management, content
publishing, post retrieval, and analytics through the social connector
abstraction layer.

All publishing operations require explicit ``PUBLISH_SOCIAL`` permission
and are never executed silently.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.factory import build_default_registry
from app.integrations.http_client import HttpClient
from app.integrations.meta_social import MetaSocialConnector
from app.integrations.social import SocialConnector

router = APIRouter()


class SocialProviderResponse(BaseModel):
    name: str
    display_name: str
    registered: bool
    configured: bool
    status: str
    capabilities: list[str] = Field(default_factory=list)


class SocialProvidersResponse(BaseModel):
    providers: dict[str, SocialProviderResponse]
    total: int


class SocialPublishRequest(BaseModel):
    page_id: str
    message: str
    link: str | None = None
    picture: str | None = None
    name: str | None = None
    description: str | None = None
    provider: str = "meta"


class SocialPublishResponse(BaseModel):
    created: bool
    post_id: str | None = None
    platform_url: str | None = None
    provider: str
    message: str | None = None


class SocialPostResponse(BaseModel):
    post_id: str | None = None
    message: str | None = None
    created_time: str | None = None
    type: str | None = None
    permalink_url: str | None = None
    shares: int = 0
    likes: int = 0
    comments: int = 0


class SocialInsightsResponse(BaseModel):
    provider: str
    entity_id: str
    summary: dict[str, Any] = Field(default_factory=dict)
    metrics: list[dict[str, Any]] = Field(default_factory=list)


class SocialAccountResponse(BaseModel):
    id: str
    provider: str
    provider_account_id: str
    name: str
    account_type: str
    status: str


# ------------------------------------------------------------------
# Provider discovery
# ------------------------------------------------------------------


@router.get(
    "/providers",
    response_model=SocialProvidersResponse,
    tags=["social"],
    summary="List available social media providers",
)
def list_providers() -> SocialProvidersResponse:
    """Return all registered social providers with their status and capabilities."""
    social = SocialConnector()
    # Register Meta if configured
    meta = MetaSocialConnector()
    if meta.is_configured:
        social.register_provider("meta", meta)

    providers = social.list_providers()
    return SocialProvidersResponse(
        providers={
            name: SocialProviderResponse(**info)
            for name, info in providers.items()
        },
        total=len(providers),
    )


# ------------------------------------------------------------------
# Meta-specific endpoints
# ------------------------------------------------------------------


@router.get(
    "/meta/pages",
    tags=["social", "meta"],
    summary="List Facebook Pages accessible with the current token",
)
def meta_list_pages() -> dict[str, Any]:
    """Discover Facebook Pages the configured token has access to."""
    connector = MetaSocialConnector()
    if not connector.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meta social integration is not configured (GOALOS_META_PAGE_ACCESS_TOKEN not set)",
        )
    try:
        result = connector.execute(
            "meta_social.list_pages", {}, permissions=set()
        )
        return result
    except (AuthenticationError, PermissionDeniedError, ConnectorError, RateLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )


@router.get(
    "/meta/pages/{page_id}/instagram",
    tags=["social", "meta"],
    summary="Get Instagram Business account linked to a Facebook Page",
)
def meta_get_instagram_account(page_id: str) -> dict[str, Any]:
    """Discover the Instagram Business account associated with a Page."""
    connector = MetaSocialConnector()
    if not connector.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meta social integration is not configured",
        )
    try:
        return connector.execute(
            "meta_social.list_instagram_accounts",
            {"page_id": page_id},
            permissions=set(),
        )
    except (AuthenticationError, PermissionDeniedError, ConnectorError, RateLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )


@router.get(
    "/meta/pages/{page_id}",
    tags=["social", "meta"],
    summary="Get Facebook Page details",
)
def meta_get_page_info(page_id: str) -> dict[str, Any]:
    """Get detailed information about a Facebook Page."""
    connector = MetaSocialConnector()
    if not connector.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meta social integration is not configured",
        )
    try:
        return connector.execute(
            "meta_social.get_page_info",
            {"page_id": page_id},
            permissions=set(),
        )
    except (AuthenticationError, PermissionDeniedError, ConnectorError, RateLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )


@router.post(
    "/meta/posts",
    response_model=SocialPublishResponse,
    tags=["social", "meta"],
    summary="Publish a post to a Facebook Page",
)
def meta_publish_post(request: SocialPublishRequest) -> SocialPublishResponse:
    """Publish content to a Facebook Page.

    Requires PUBLISH_SOCIAL permission. The operation is persisted as an
    execution record for audit.
    """
    connector = MetaSocialConnector()
    if not connector.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meta social integration is not configured",
        )
    params: dict[str, Any] = {
        "page_id": request.page_id,
        "message": request.message,
    }
    if request.link:
        params["link"] = request.link
    if request.picture:
        params["picture"] = request.picture
    if request.name:
        params["name"] = request.name
    if request.description:
        params["description"] = request.description

    try:
        from app.agents.permissions import Permission

        result = connector.execute(
            "meta_social.publish_post",
            params,
            permissions={Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL},
        )
        return SocialPublishResponse(
            created=result.get("created", False),
            post_id=result.get("post_id"),
            platform_url=result.get("platform_url"),
            provider="meta",
        )
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except (AuthenticationError, ConnectorError, RateLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    except CapabilityUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.get(
    "/meta/posts/{post_id}",
    response_model=SocialPostResponse,
    tags=["social", "meta"],
    summary="Get a Facebook post",
)
def meta_get_post(post_id: str) -> SocialPostResponse:
    """Retrieve a specific post from a Facebook Page."""
    connector = MetaSocialConnector()
    if not connector.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meta social integration is not configured",
        )
    try:
        result = connector.execute(
            "meta_social.get_post",
            {"post_id": post_id},
            permissions=set(),
        )
        return SocialPostResponse(
            post_id=result.get("post_id"),
            message=result.get("message"),
            created_time=result.get("created_time"),
            type=result.get("type"),
            permalink_url=result.get("permalink_url"),
            shares=result.get("shares", 0),
            likes=result.get("likes", 0),
            comments=result.get("comments", 0),
        )
    except (AuthenticationError, PermissionDeniedError, ConnectorError, RateLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )


@router.get(
    "/meta/pages/{page_id}/insights",
    tags=["social", "meta"],
    summary="Get Facebook Page engagement insights",
)
def meta_get_page_insights(
    page_id: str,
    metrics: str | None = None,
    period: str = "day",
) -> dict[str, Any]:
    """Get engagement insights for a Facebook Page."""
    connector = MetaSocialConnector()
    if not connector.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meta social integration is not configured",
        )
    params: dict[str, Any] = {"page_id": page_id, "period": period}
    if metrics:
        params["metrics"] = metrics
    try:
        from app.agents.permissions import Permission

        return connector.execute(
            "meta_social.get_page_insights",
            params,
            permissions={Permission.READ_SOCIAL},
        )
    except (AuthenticationError, PermissionDeniedError, ConnectorError, RateLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )


@router.get(
    "/meta/posts/{post_id}/insights",
    tags=["social", "meta"],
    summary="Get Facebook post engagement insights",
)
def meta_get_post_insights(
    post_id: str,
    metrics: str | None = None,
) -> dict[str, Any]:
    """Get engagement insights for a specific Facebook post."""
    connector = MetaSocialConnector()
    if not connector.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meta social integration is not configured",
        )
    params: dict[str, Any] = {"post_id": post_id}
    if metrics:
        params["metrics"] = metrics
    try:
        from app.agents.permissions import Permission

        return connector.execute(
            "meta_social.get_post_insights",
            params,
            permissions={Permission.READ_SOCIAL},
        )
    except (AuthenticationError, PermissionDeniedError, ConnectorError, RateLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
