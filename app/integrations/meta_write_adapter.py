"""Meta Ads write adapter for GoalOS.

Extends the existing MetaAdsConnector with controlled write operations:
create campaign, create ad set, create ad, update status, update budget.

Every write operation is typed and validated — no arbitrary API calls.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.integrations.http_client import HttpClient
from app.integrations.meta_ads import _GRAPH_API, MetaAdsConnector

logger = logging.getLogger(__name__)


class MetaWriteAdapter(MetaAdsConnector):
    """Meta Marketing API write adapter.

    Extends MetaAdsConnector with controlled write operations.
    All writes go through typed methods — no arbitrary API execution.
    """

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        access_token: str | None = None,
        ad_account_id: str | None = None,
    ) -> None:
        super().__init__(client=client, access_token=access_token, ad_account_id=ad_account_id)

    def create_campaign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Meta campaign."""
        payload = {
            "name": params["name"],
            "objective": params["objective"],
            "status": params.get("status", "PAUSED"),
            "special_ad_categories": params.get("special_ad_categories", []),
        }
        if params.get("daily_budget"):
            payload["daily_budget"] = str(int(params["daily_budget"] * 100))  # cents
        if params.get("lifetime_budget"):
            payload["lifetime_budget"] = str(int(params["lifetime_budget"] * 100))

        return self._post(f"{self._account()}/campaigns", payload)

    def create_adset(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Meta ad set."""
        # Resolve campaign ID from name or direct ID
        campaign_id = params.get("campaign_id") or self._resolve_campaign_id(params.get("campaign", ""))

        payload = {
            "name": params["name"],
            "campaign_id": campaign_id,
            "daily_budget": str(int(params.get("daily_budget", 0) * 100)),
            "bid_strategy": params.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP"),
            "optimization_goal": params.get("optimization_goal", "LINK_CLICKS"),
            "billing_event": params.get("billing_event", "IMPRESSIONS"),
            "targeting": params.get("targeting", {}),
            "status": params.get("status", "PAUSED"),
        }

        return self._post(f"{self._account()}/adsets", payload)

    def create_ad(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Meta ad."""
        adset_id = params.get("adset_id") or self._resolve_adset_id(params.get("adset", ""))
        creative_id = params.get("creative_id") or self._resolve_creative_id(params.get("creative", ""))

        payload = {
            "name": params["name"],
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": params.get("status", "PAUSED"),
        }

        return self._post(f"{self._account()}/ads", payload)

    def create_creative(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Meta creative."""
        payload = {
            "name": params["name"],
            "object_type": params.get("object_type", "SHAREABLE_CONTENT"),
        }

        # Link data
        link_data = {}
        if params.get("title"):
            link_data["name"] = params["title"]
        if params.get("body"):
            link_data["message"] = params["body"]
        if params.get("link_url"):
            link_data["link"] = params["link_url"]
        if params.get("image_url"):
            link_data["picture"] = params["image_url"]
        if params.get("description"):
            link_data["description"] = params["description"]

        cta_type = params.get("call_to_action_type", "LEARN_MORE")
        if cta_type:
            link_data["call_to_action"] = {
                "type": cta_type,
                "value": {"link": params.get("link_url", "")},
            }

        if link_data:
            payload["link_data"] = link_data

        return self._post(f"{self._account()}/adcreatives", payload)

    def update_campaign(self, campaign_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Update a Meta campaign."""
        return self._post(campaign_id, params)

    def update_adset(self, adset_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Update a Meta ad set."""
        return self._post(adset_id, params)

    def update_ad(self, ad_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Update a Meta ad."""
        return self._post(ad_id, params)

    def update_status(self, entity_id: str, status: str) -> dict[str, Any]:
        """Update the status of any Meta entity."""
        return self._post(entity_id, {"status": status})

    def update_budget(self, entity_id: str, new_budget: float) -> dict[str, Any]:
        """Update the daily budget of a campaign or ad set."""
        return self._post(entity_id, {"daily_budget": str(int(new_budget * 100))})

    def duplicate_entity(self, entity_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Duplicate a campaign, ad set, or ad."""
        # Read the original
        original = self._get(entity_id)
        # Create a copy with new name
        copy_params = {**original}
        copy_params["name"] = params.get("name", f"{original.get('name', '')} (Copy)")
        copy_params.pop("id", None)
        copy_params.pop("created_time", None)
        copy_params.pop("updated_time", None)

        # Determine entity type from the original
        if "campaign_id" in original:
            return self._post(f"{self._account()}/adsets", copy_params)
        elif "adset_id" in original:
            return self._post(f"{self._account()}/ads", copy_params)
        else:
            return self._post(f"{self._account()}/campaigns", copy_params)

    # -- Internal HTTP helpers --

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST to the Graph API."""
        url = f"{_GRAPH_API}/{path}"
        response = self.client.post(url, headers=self._headers(), json=data)
        payload = json.loads(response.text)
        if "error" in payload:
            from app.integrations.exceptions import ConfigurationError
            raise ConfigurationError(
                f"Meta API error {payload['error'].get('code')}: "
                f"{payload['error'].get('message')}"
            )
        return payload

    def _get(self, path: str) -> dict[str, Any]:
        """GET from the Graph API."""
        url = f"{_GRAPH_API}/{path}"
        response = self.client.get(url, headers=self._headers())
        payload = json.loads(response.text)
        if "error" in payload:
            from app.integrations.exceptions import ConfigurationError
            raise ConfigurationError(
                f"Meta API error {payload['error'].get('code')}: "
                f"{payload['error'].get('message')}"
            )
        return payload

    def _resolve_campaign_id(self, name_or_id: str) -> str:
        """Resolve a campaign name to its Meta ID."""
        if name_or_id.startswith("act_") or name_or_id.isdigit():
            return name_or_id
        result = self._list(f"{self._account()}/campaigns", {"fields": "id,name", "limit": 100}, key="data")
        for item in result.get("items", []):
            if item.get("name") == name_or_id:
                return item["id"]
        raise ValueError(f"Campaign not found: {name_or_id}")

    def _resolve_adset_id(self, name_or_id: str) -> str:
        """Resolve an ad set name to its Meta ID."""
        if name_or_id.startswith("act_") or name_or_id.isdigit():
            return name_or_id
        result = self._list(f"{self._account()}/adsets", {"fields": "id,name", "limit": 100}, key="data")
        for item in result.get("items", []):
            if item.get("name") == name_or_id:
                return item["id"]
        raise ValueError(f"Ad set not found: {name_or_id}")

    def _resolve_creative_id(self, name_or_id: str) -> str:
        """Resolve a creative name to its Meta ID."""
        if name_or_id.startswith("act_") or name_or_id.isdigit():
            return name_or_id
        result = self._list(f"{self._account()}/adcreatives", {"fields": "id,name", "limit": 100}, key="data")
        for item in result.get("items", []):
            if item.get("name") == name_or_id:
                return item["id"]
        raise ValueError(f"Creative not found: {name_or_id}")
