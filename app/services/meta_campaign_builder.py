"""Meta Campaign Builder for GoalOS.

Structured campaign creation following the Meta hierarchy:
Campaign → Ad Set → Ad → Creative

Validates before anything is sent to Meta. Supports dry-run mode
where the agent can prepare a complete campaign without spending money.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CampaignConfig:
    """Configuration for a Meta campaign."""
    name: str
    objective: str  # OUT_OF_AWARENESS, REACH, OUTBOUND_CLICKS, ENGAGEMENT, LEADS, APP_PROMOTION, SALES, THRUPLAY
    status: str = "PAUSED"
    daily_budget: float | None = None
    lifetime_budget: float | None = None
    currency: str = "USD"
    start_time: str | None = None
    stop_time: str | None = None


@dataclass
class AdSetConfig:
    """Configuration for a Meta ad set."""
    name: str
    campaign_name: str
    daily_budget: float | None = None
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP"
    optimization_goal: str = "LINK_CLICKS"
    billing_event: str = "IMPRESSIONS"
    targeting: dict[str, Any] = field(default_factory=dict)
    placement_special_platforms: list[str] = field(default_factory=list)


@dataclass
class AdConfig:
    """Configuration for a Meta ad."""
    name: str
    adset_name: str
    campaign_name: str
    creative: dict[str, Any] = field(default_factory=dict)
    tracking_specs: dict[str, Any] | None = None


@dataclass
class CreativeConfig:
    """Configuration for a Meta creative."""
    name: str
    object_type: str = "SHAREABLE_CONTENT"
    title: str = ""
    body: str = ""
    image_url: str | None = None
    video_id: str | None = None
    link_url: str = ""
    call_to_action_type: str = "LEARN_MORE"
    description: str = ""


@dataclass
class CampaignBlueprint:
    """Complete campaign blueprint ready for validation and execution."""
    campaign: CampaignConfig
    ad_sets: list[AdSetConfig] = field(default_factory=list)
    ads: list[AdConfig] = field(default_factory=list)
    creatives: list[CreativeConfig] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    estimated_daily_spend: float = 0.0
    is_valid: bool = False


# Valid Meta objectives
_VALID_OBJECTIVES = {
    "OUT_OF_AWARENESS", "REACH", "OUTBOUND_CLICKS", "ENGAGEMENT",
    "LEADS", "APP_PROMOTION", "SALES", "THRUPLAY",
}

# Valid optimization goals
_VALID_OPTIMIZATION_GOALS = {
    "LINK_CLICKS", "IMPRESSIONS", "REACH", "LANDING_PAGE_VIEWS",
    "OFFSITE_CONVERSIONS", "VALUE", "LEAD_GENERATION", "APP_INSTALLS",
}

# Valid CTA types
_VALID_CTA_TYPES = {
    "LEARN_MORE", "SHOP_NOW", "SIGN_UP", "DOWNLOAD", "BOOK_TRAVEL",
    "CONTACT_US", "APPLY_NOW", "SUBSCRIBE", "WATCH_MORE", "LISTEN_NOW",
}


def build_campaign(
    campaign: CampaignConfig,
    ad_sets: list[AdSetConfig] | None = None,
    ads: list[AdConfig] | None = None,
    creatives: list[CreativeConfig] | None = None,
) -> CampaignBlueprint:
    """Build a campaign blueprint and validate it.

    Returns a CampaignBlueprint with validation results.
    Does NOT send anything to Meta.
    """
    blueprint = CampaignBlueprint(
        campaign=campaign,
        ad_sets=ad_sets or [],
        ads=ads or [],
        creatives=creatives or [],
    )

    # Validate campaign
    _validate_campaign(blueprint)

    # Validate ad sets
    _validate_ad_sets(blueprint)

    # Validate ads
    _validate_ads(blueprint)

    # Validate creatives
    _validate_creatives(blueprint)

    # Estimate budget
    blueprint.estimated_daily_spend = _estimate_daily_spend(blueprint)

    blueprint.is_valid = len(blueprint.validation_errors) == 0

    return blueprint


def validate_campaign蓝图(blueprint: CampaignBlueprint) -> CampaignBlueprint:
    """Re-validate an existing blueprint."""
    blueprint.validation_errors.clear()
    blueprint.validation_warnings.clear()
    _validate_campaign(blueprint)
    _validate_ad_sets(blueprint)
    _validate_ads(blueprint)
    _validate_creatives(blueprint)
    blueprint.estimated_daily_spend = _estimate_daily_spend(blueprint)
    blueprint.is_valid = len(blueprint.validation_errors) == 0
    return blueprint


def blueprint_to_dry_run(blueprint: CampaignBlueprint) -> dict[str, Any]:
    """Convert a blueprint to a dry-run representation.

    Shows exactly what would be sent to Meta without actually sending it.
    """
    return {
        "mode": "dry_run",
        "is_valid": blueprint.is_valid,
        "errors": blueprint.validation_errors,
        "warnings": blueprint.validation_warnings,
        "estimated_daily_spend": blueprint.estimated_daily_spend,
        "campaign": {
            "name": blueprint.campaign.name,
            "objective": blueprint.campaign.objective,
            "status": blueprint.campaign.status,
            "daily_budget": blueprint.campaign.daily_budget,
            "lifetime_budget": blueprint.campaign.lifetime_budget,
            "currency": blueprint.campaign.currency,
        },
        "ad_sets": [
            {
                "name": adset.name,
                "daily_budget": adset.daily_budget,
                "bid_strategy": adset.bid_strategy,
                "optimization_goal": adset.optimization_goal,
                "targeting_summary": _summarize_targeting(adset.targeting),
            }
            for adset in blueprint.ad_sets
        ],
        "ads": [
            {
                "name": ad.name,
                "creative_name": ad.creative.get("name", ""),
            }
            for ad in blueprint.ads
        ],
        "creatives": [
            {
                "name": c.name,
                "type": c.object_type,
                "has_image": bool(c.image_url),
                "has_video": bool(c.video_id),
                "cta": c.call_to_action_type,
            }
            for c in blueprint.creatives
        ],
        "meta_api_actions": _build_api_actions(blueprint),
    }


def _validate_campaign(bp: CampaignBlueprint) -> None:
    c = bp.campaign
    if not c.name:
        bp.validation_errors.append("Campaign name is required")
    if c.objective not in _VALID_OBJECTIVES:
        bp.validation_errors.append(f"Invalid objective: {c.objective}")
    if c.daily_budget is not None and c.daily_budget < 1.0:
        bp.validation_errors.append("Daily budget must be at least $1.00")
    if c.lifetime_budget is not None and c.lifetime_budget < 1.0:
        bp.validation_errors.append("Lifetime budget must be at least $1.00")
    if not bp.ad_sets:
        bp.validation_warnings.append("No ad sets defined — at least one is needed")


def _validate_ad_sets(bp: CampaignBlueprint) -> None:
    for i, adset in enumerate(bp.ad_sets):
        if not adset.name:
            bp.validation_errors.append(f"Ad set #{i+1} name is required")
        if adset.optimization_goal not in _VALID_OPTIMIZATION_GOALS:
            bp.validation_errors.append(
                f"Ad set '{adset.name}' has invalid optimization goal: {adset.optimization_goal}"
            )
        if adset.daily_budget is not None and adset.daily_budget < 1.0:
            bp.validation_errors.append(
                f"Ad set '{adset.name}' daily budget must be at least $1.00"
            )


def _validate_ads(bp: CampaignBlueprint) -> None:
    for i, ad in enumerate(bp.ads):
        if not ad.name:
            bp.validation_errors.append(f"Ad #{i+1} name is required")
        if not ad.creative:
            bp.validation_warnings.append(f"Ad '{ad.name}' has no creative attached")


def _validate_creatives(bp: CampaignBlueprint) -> None:
    for i, c in enumerate(bp.creatives):
        if not c.name:
            bp.validation_errors.append(f"Creative #{i+1} name is required")
        if c.call_to_action_type not in _VALID_CTA_TYPES:
            bp.validation_errors.append(
                f"Creative '{c.name}' has invalid CTA: {c.call_to_action_type}"
            )
        if not c.image_url and not c.video_id and not c.body:
            bp.validation_warnings.append(
                f"Creative '{c.name}' has no image, video, or body text"
            )


def _estimate_daily_spend(bp: CampaignBlueprint) -> float:
    if bp.campaign.daily_budget:
        return bp.campaign.daily_budget
    total_adset_budget = sum(a.daily_budget or 0 for a in bp.ad_sets)
    return total_adset_budget


def _summarize_targeting(targeting: dict[str, Any]) -> str:
    parts = []
    if targeting.get("age_min") and targeting.get("age_max"):
        parts.append(f"Age {targeting['age_min']}-{targeting['age_max']}")
    if targeting.get("genders"):
        parts.append(f"Genders: {targeting['genders']}")
    if targeting.get("interests"):
        parts.append(f"{len(targeting['interests'])} interests")
    if targeting.get("locations"):
        parts.append(f"{len(targeting['locations'])} locations")
    return ", ".join(parts) if parts else "No targeting specified"


def _build_api_actions(bp: CampaignBlueprint) -> list[dict[str, Any]]:
    """Build the Meta API action sequence for this blueprint."""
    actions = []
    actions.append({
        "type": "create_campaign",
        "parameters": {
            "name": bp.campaign.name,
            "objective": bp.campaign.objective,
            "status": bp.campaign.status,
            "special_ad_categories": [],
        },
    })
    for adset in bp.ad_sets:
        actions.append({
            "type": "create_adset",
            "parameters": {
                "name": adset.name,
                "campaign": bp.campaign.name,
                "daily_budget": adset.daily_budget,
                "bid_strategy": adset.bid_strategy,
                "optimization_goal": adset.optimization_goal,
                "billing_event": adset.billing_event,
                "targeting": adset.targeting,
            },
        })
    for creative in bp.creatives:
        actions.append({
            "type": "create_creative",
            "parameters": {
                "name": creative.name,
                "object_type": creative.object_type,
                "title": creative.title,
                "body": creative.body,
                "image_url": creative.image_url,
                "link_url": creative.link_url,
                "call_to_action_type": creative.call_to_action_type,
            },
        })
    for ad in bp.ads:
        actions.append({
            "type": "create_ad",
            "parameters": {
                "name": ad.name,
                "adset": ad.adset_name,
                "creative": ad.creative.get("name", ""),
            },
        })
    return actions
