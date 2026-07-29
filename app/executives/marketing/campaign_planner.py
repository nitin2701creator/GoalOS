"""Deterministic planning helpers for the Marketing executive."""

from __future__ import annotations

from datetime import date, timedelta

from .marketing_models import AudienceSegment, BudgetPlan, CreativeAsset, MarketingCampaign


class CampaignPlanner:
    def campaign_plan(self, name: str, objective: str, channel: str, budget: float = 0.0) -> MarketingCampaign:
        return MarketingCampaign(name=name, objective=objective, channel=channel, budget=budget)

    def audience_plan(self, name: str, description: str, **criteria: object) -> AudienceSegment:
        return AudienceSegment(name=name, description=description, criteria=criteria)

    def budget_plan(self, total_budget: float, days: int = 30, currency: str = "USD") -> BudgetPlan:
        if days <= 0:
            raise ValueError("days must be positive")
        return BudgetPlan(total_budget=total_budget, daily_budget=total_budget / days, currency=currency)

    def creative_plan(self, name: str, asset_type: str, channel: str | None = None) -> CreativeAsset:
        return CreativeAsset(name=name, asset_type=asset_type, channel=channel)

    def ab_test_plan(self, hypothesis: str, control: str, variant: str, metric: str = "Conversion Rate") -> dict[str, str]:
        return {"hypothesis": hypothesis, "control": control, "variant": variant, "primary_metric": metric}

    def weekly_content_calendar(self, start_date: date | None = None, channels: tuple[str, ...] = ("Instagram", "Facebook")) -> list[dict[str, object]]:
        start = start_date or date.today()
        return [{"date": start + timedelta(days=offset), "channel": channels[offset % len(channels)], "status": "planned"} for offset in range(7)]

    # Verb-first aliases make the planner convenient for command-oriented callers.
    plan_campaign = campaign_plan
    plan_audience = audience_plan
    plan_budget = budget_plan
    plan_creative = creative_plan
    plan_ab_test = ab_test_plan
    plan_weekly_content_calendar = weekly_content_calendar
