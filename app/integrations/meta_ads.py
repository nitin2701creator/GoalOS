"""Meta Marketing API integration (read-only production surface).

``MetaAdsConnector`` lists ad accounts, campaigns, ad sets, and ads and
retrieves insights through the Meta Graph API over the shared HTTP client.
Write capabilities (``meta.campaigns.write``, ``meta.ads.write``) are
declared with their ``MODIFY_ADS`` permission requirement but are NOT
enabled — invoking one raises an explicit error, so no campaign or budget
is ever changed automatically.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from app.agents.permissions import Permission
from app.integrations.exceptions import (
    CapabilityUnavailableError,
    ConfigurationError,
)
from app.integrations.http_client import HttpClient
from app.integrations.integration_connector import IntegrationConnector

_GRAPH_API = "https://graph.facebook.com/v21.0"
_INSIGHT_FIELDS = (
    "campaign_name,adset_name,ad_name,impressions,clicks,spend,reach,"
    "ctr,cpc,cpm,frequency,actions,date_start,date_stop"
)


class MetaAdsConnector(IntegrationConnector):
    """Meta Marketing API connector for read-only advertising data."""

    required_env_vars: tuple[str, ...] = ("GOALOS_META_ACCESS_TOKEN",)
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "meta.ads.read": Permission.READ_ANALYTICS,
        "meta.campaigns.read": Permission.READ_ANALYTICS,
        "meta.adsets.read": Permission.READ_ANALYTICS,
        "meta.ads.list": Permission.READ_ANALYTICS,
        "meta.insights.read": Permission.READ_ANALYTICS,
        "meta.campaigns.write": Permission.MODIFY_ADS,
        "meta.ads.write": Permission.MODIFY_ADS,
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        access_token: str | None = None,
        ad_account_id: str | None = None,
    ) -> None:
        super().__init__(
            name="meta_ads",
            description="Meta Marketing API integration",
        )
        self.client = client or HttpClient()
        self.access_token = access_token or self._env("GOALOS_META_ACCESS_TOKEN") or ""
        self.ad_account_id = ad_account_id or self._env("GOALOS_META_AD_ACCOUNT_ID") or ""

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "meta.ads.read",
            "meta.campaigns.read",
            "meta.adsets.read",
            "meta.ads.list",
            "meta.insights.read",
            "meta.campaigns.write",
            "meta.ads.write",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        if not self.access_token:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                "missing environment configuration: GOALOS_META_ACCESS_TOKEN",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability in ("meta.campaigns.write", "meta.ads.write"):
            raise CapabilityUnavailableError(
                f"capability '{capability}' is not enabled; no campaign or ad "
                "writes are performed automatically"
            )
        if capability == "meta.ads.read":
            return self._list("me/adaccounts", params, key="adaccounts")
        if capability == "meta.campaigns.read":
            return self._list(f"{self._account()}/campaigns", params, key="data")
        if capability == "meta.adsets.read":
            return self._list(f"{self._account()}/adsets", params, key="data")
        if capability == "meta.ads.list":
            return self._list(f"{self._account()}/ads", params, key="data")
        if capability == "meta.insights.read":
            return self._insights(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    def _list(self, path: str, params: dict[str, Any], *, key: str) -> dict[str, Any]:
        fields = params.get("fields")
        query: dict[str, Any] = {
            "fields": fields or "id,name,status",
            "limit": int(params.get("limit") or 50),
        }
        if params.get("campaign_id"):
            query["campaign_id"] = params["campaign_id"]
        response = self.client.get(
            f"{_GRAPH_API}/{path}",
            headers=self._headers(),
            params=query,
        )
        payload = json.loads(response.text)
        if "error" in payload:
            raise ConfigurationError(
                f"Meta API error {payload['error'].get('code')}: "
                f"{payload['error'].get('message')}"
            )
        items = payload.get(key) or payload.get("data") or []
        return {"path": path, "total": len(items), "items": items}

    def _insights(self, params: dict[str, Any]) -> dict[str, Any]:
        date_presets = params.get("date_presets") or "last_30d"
        time_increment = params.get("time_increment")
        query: dict[str, Any] = {
            "fields": _INSIGHT_FIELDS,
            "date_presets": date_presets,
            "limit": int(params.get("limit") or 50),
        }
        if time_increment:
            query["time_increment"] = time_increment
        if params.get("level"):
            query["level"] = params["level"]
        response = self.client.get(
            f"{_GRAPH_API}/{self._account()}/insights",
            headers=self._headers(),
            params=query,
        )
        payload = json.loads(response.text)
        if "error" in payload:
            raise ConfigurationError(
                f"Meta API error {payload['error'].get('code')}: "
                f"{payload['error'].get('message')}"
            )
        items = payload.get("data") or []
        summary = {"spend": 0.0, "impressions": 0, "clicks": 0}
        for item in items:
            try:
                summary["spend"] += float(item.get("spend") or 0)
                summary["impressions"] += int(item.get("impressions") or 0)
                summary["clicks"] += int(item.get("clicks") or 0)
            except (TypeError, ValueError):
                continue
        return {
            "date_presets": date_presets,
            "total": len(items),
            "items": items,
            "summary": summary,
        }

    def _account(self) -> str:
        if not self.ad_account_id:
            raise ConfigurationError(
                "GOALOS_META_AD_ACCOUNT_ID is required for campaign/ad reads"
            )
        return f"act_{self.ad_account_id.lstrip('act_')}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}
