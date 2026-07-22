"""Stateful, network-free service layer for marketing operations."""

from __future__ import annotations

from .marketing_models import MarketingCampaign, MarketingKPI, MarketingSummary


class MarketingService:
    """In-memory campaign store and KPI calculator.

    Integration clients deliberately remain placeholders so this foundation is
    safe to run without credentials or external side effects.
    """

    def __init__(self) -> None:
        self._campaigns: dict[str, MarketingCampaign] = {}

    def create_campaign(self, campaign: MarketingCampaign) -> MarketingCampaign:
        self._campaigns[campaign.id] = campaign
        return campaign

    def get_campaign(self, campaign_id: str) -> MarketingCampaign:
        try:
            return self._campaigns[campaign_id]
        except KeyError as exc:
            raise ValueError(f"Unknown campaign: {campaign_id}") from exc

    def campaigns(self) -> tuple[MarketingCampaign, ...]:
        return tuple(self._campaigns.values())

    def update_campaign(self, campaign_id: str, **changes: object) -> MarketingCampaign:
        campaign = self.get_campaign(campaign_id)
        updated = campaign.model_copy(update=changes)
        self._campaigns[campaign_id] = updated
        return updated

    def summary(self) -> MarketingSummary:
        campaigns = self.campaigns()
        spend = sum(campaign.spend for campaign in campaigns)
        revenue = sum(campaign.revenue for campaign in campaigns)
        return MarketingSummary(
            campaign_count=len(campaigns), active_campaign_count=sum(c.status == "active" for c in campaigns),
            total_budget=sum(c.budget for c in campaigns), total_spend=spend, total_revenue=revenue,
            kpis=self.kpis(),
        )

    def kpis(self) -> list[MarketingKPI]:
        campaigns = self.campaigns()
        spend = sum(c.spend for c in campaigns)
        revenue = sum(c.revenue for c in campaigns)
        # Placeholder delivery metrics remain zero until platform integrations arrive.
        return [
            MarketingKPI(name="ROAS", value=revenue / spend if spend else 0.0, unit="x"),
            MarketingKPI(name="CAC", value=0.0, unit="USD"),
            MarketingKPI(name="CTR", value=0.0, unit="%"),
            MarketingKPI(name="CPC", value=0.0, unit="USD"),
            MarketingKPI(name="CPM", value=0.0, unit="USD"),
            MarketingKPI(name="Conversion Rate", value=0.0, unit="%"),
        ]
