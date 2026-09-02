"""Meta Ads optimization engine for GoalOS.

Analyzes performance data and produces controlled recommendations.
Recommends actions but does NOT blindly execute them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OptimizationRecommendation:
    """A single optimization recommendation."""
    action: str  # pause_ad, activate_ad, increase_budget, etc.
    entity_type: str  # campaign, adset, ad
    entity_id: str
    entity_name: str
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5  # 0.0 - 1.0
    expected_impact: str = ""
    risk_level: str = "medium"
    requires_approval: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)


class MetaOptimizationEngine:
    """Analyzes Meta Ads performance and produces optimization recommendations."""

    def analyze_and_recommend(
        self,
        campaigns: list[dict[str, Any]] | None = None,
        adsets: list[dict[str, Any]] | None = None,
        ads: list[dict[str, Any]] | None = None,
        performance: list[dict[str, Any]] | None = None,
    ) -> list[OptimizationRecommendation]:
        """Analyze performance and produce recommendations."""
        recommendations = []
        campaigns = campaigns or []
        adsets = adsets or []
        ads = ads or []
        performance = performance or []

        # Build performance lookup
        perf_by_entity: dict[str, dict] = {}
        for p in performance:
            eid = p.get("id", "")
            if eid:
                perf_by_entity[eid] = p

        # Analyze ads
        for ad in ads:
            ad_id = ad.get("id", "")
            perf = perf_by_entity.get(ad_id, {})
            recs = self._analyze_ad(ad, perf)
            recommendations.extend(recs)

        # Analyze ad sets
        for adset in adsets:
            adset_id = adset.get("id", "")
            perf = perf_by_entity.get(adset_id, {})
            recs = self._analyze_adset(adset, perf)
            recommendations.extend(recs)

        # Analyze campaigns
        for campaign in campaigns:
            campaign_id = campaign.get("id", "")
            perf = perf_by_entity.get(campaign_id, {})
            recs = self._analyze_campaign(campaign, perf)
            recommendations.extend(recs)

        # Sort by confidence (highest first)
        recommendations.sort(key=lambda r: r.confidence, reverse=True)

        return recommendations

    def _analyze_ad(self, ad: dict, perf: dict) -> list[OptimizationRecommendation]:
        recs = []
        ad_id = ad.get("id", "")
        ad_name = ad.get("name", "")
        status = ad.get("status", "")
        ctr = float(perf.get("ctr", 0))
        frequency = float(perf.get("frequency", 0))
        cpc = float(perf.get("cpc", 0))
        spend = float(perf.get("spend", 0))

        # Pause underperforming ad
        if status == "ACTIVE" and ctr < 0.5 and spend > 10:
            recs.append(OptimizationRecommendation(
                action="pause_ad",
                entity_type="ad",
                entity_id=ad_id,
                entity_name=ad_name,
                reason=f"CTR {ctr:.2f}% is critically low with ${spend:.2f} spent",
                metrics={"ctr": ctr, "spend": spend, "cpc": cpc},
                confidence=0.8,
                expected_impact="Stop wasting budget on underperforming creative",
                risk_level="low",
                requires_approval=True,
                parameters={"ad_id": ad_id},
            ))

        # Activate approved ad
        if status == "PAUSED" and ctr > 2.0:
            recs.append(OptimizationRecommendation(
                action="activate_ad",
                entity_type="ad",
                entity_id=ad_id,
                entity_name=ad_name,
                reason=f"CTR {ctr:.2f}% is strong — consider activating",
                metrics={"ctr": ctr},
                confidence=0.6,
                expected_impact="Potential impressions and conversions",
                risk_level="medium",
                requires_approval=True,
                parameters={"ad_id": ad_id},
            ))

        # Creative fatigue
        if frequency > 4.0 and status == "ACTIVE":
            recs.append(OptimizationRecommendation(
                action="replace_creative",
                entity_type="ad",
                entity_id=ad_id,
                entity_name=ad_name,
                reason=f"Frequency {frequency:.1f} indicates creative fatigue",
                metrics={"frequency": frequency, "ctr": ctr},
                confidence=0.7,
                expected_impact="Refresh creative to reduce fatigue",
                risk_level="medium",
                requires_approval=True,
                parameters={"ad_id": ad_id},
            ))

        return recs

    def _analyze_adset(self, adset: dict, perf: dict) -> list[OptimizationRecommendation]:
        recs = []
        adset_id = adset.get("id", "")
        adset_name = adset.get("name", "")
        daily_budget = float(adset.get("daily_budget", 0) or 0)

        # Budget optimization
        if daily_budget > 0 and perf:
            spend = float(perf.get("spend", 0))
            conversions = int(perf.get("actions", [{}])[0].get("value", 0) if perf.get("actions") else 0)
            if spend > daily_budget * 0.8 and conversions == 0:
                recs.append(OptimizationRecommendation(
                    action="decrease_budget",
                    entity_type="adset",
                    entity_id=adset_id,
                    entity_name=adset_name,
                    reason=f"High spend (${spend:.2f}) with no conversions",
                    metrics={"spend": spend, "daily_budget": daily_budget, "conversions": conversions},
                    confidence=0.6,
                    expected_impact="Reduce wasted spend",
                    risk_level="low",
                    requires_approval=True,
                    parameters={"adset_id": adset_id, "new_budget": daily_budget * 0.5},
                ))

        return recs

    def _analyze_campaign(self, campaign: dict, perf: dict) -> list[OptimizationRecommendation]:
        recs = []
        # Campaign-level analysis is typically done through ad set aggregation
        # Keep this minimal — detailed analysis happens at adset/ad level
        return recs
