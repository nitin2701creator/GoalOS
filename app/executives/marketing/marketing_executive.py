"""Marketing executive implementation and safe campaign command dispatcher."""

from __future__ import annotations

from typing import Any

try:  # The normal application runtime provides this shared contract.
    from app.executives.base_executive import BaseExecutive
except ModuleNotFoundError:  # Allows this isolated foundation package to run independently.
    class BaseExecutive:  # type: ignore[no-redef]
        def __init__(self, name: str, description: str) -> None:
            self.name, self.description = name, description

from .campaign_planner import CampaignPlanner
from .marketing_models import CampaignRecommendation, MarketingCampaign, MarketingKPI, MarketingSummary
from .marketing_service import MarketingService


class MarketingExecutive(BaseExecutive):
    INTEGRATIONS = ("Meta Ads", "Google Analytics 4", "Google Search Console", "WooCommerce", "Facebook", "Instagram", "LinkedIn", "Reddit", "Email")

    def __init__(self, service: MarketingService | None = None, planner: CampaignPlanner | None = None) -> None:
        super().__init__(name="Marketing Executive", description="Plans, executes, and monitors marketing campaigns.")
        self.service = service or MarketingService()
        self.planner = planner or CampaignPlanner()
        self._initialized = False

    def initialize(self) -> None:
        self._initialized = True

    def shutdown(self) -> None:
        self._initialized = False

    def health_check(self) -> bool:
        return self._initialized

    def get_summary(self) -> MarketingSummary:
        return self.service.summary()

    def get_kpis(self) -> tuple[MarketingKPI, ...]:
        return tuple(self.service.kpis())

    def get_alerts(self) -> tuple[dict[str, str], ...]:
        return ()

    def get_priorities(self) -> tuple[str, ...]:
        return ("Review campaign performance", "Publish this week's content calendar")

    def get_recommendations(self) -> tuple[CampaignRecommendation, ...]:
        return (CampaignRecommendation(title="Connect marketing data sources", rationale="Live delivery data is required for optimization.", action="connect_integrations", priority="high"),)

    def supported_integrations(self) -> tuple[str, ...]:
        return self.INTEGRATIONS

    def plan_campaign(self, *args: Any, **kwargs: Any) -> MarketingCampaign:
        return self.planner.plan_campaign(*args, **kwargs)

    def plan_audience(self, *args: Any, **kwargs: Any) -> Any:
        return self.planner.plan_audience(*args, **kwargs)

    def plan_budget(self, *args: Any, **kwargs: Any) -> Any:
        return self.planner.plan_budget(*args, **kwargs)

    def plan_creative(self, *args: Any, **kwargs: Any) -> Any:
        return self.planner.plan_creative(*args, **kwargs)

    def plan_ab_test(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        return self.planner.plan_ab_test(*args, **kwargs)

    def plan_weekly_content_calendar(self, *args: Any, **kwargs: Any) -> list[dict[str, object]]:
        return self.planner.plan_weekly_content_calendar(*args, **kwargs)

    def _metric(self, name: str) -> float:
        return next(kpi.value for kpi in self.get_kpis() if kpi.name == name)

    def monitor_roas(self) -> float:
        return self._metric("ROAS")

    def monitor_cac(self) -> float:
        return self._metric("CAC")

    def monitor_ctr(self) -> float:
        return self._metric("CTR")

    def monitor_cpc(self) -> float:
        return self._metric("CPC")

    def monitor_cpm(self) -> float:
        return self._metric("CPM")

    def monitor_conversion_rate(self) -> float:
        return self._metric("Conversion Rate")

    def execute(self, action: str, **kwargs: Any) -> Any:
        commands = {
            "create_campaign": self.create_campaign, "update_campaign": self.update_campaign,
            "pause_campaign": self.pause_campaign, "resume_campaign": self.resume_campaign,
            "duplicate_campaign": self.duplicate_campaign, "archive_campaign": self.archive_campaign,
        }
        try:
            return commands[action](**kwargs)
        except KeyError as exc:
            raise ValueError(f"Unsupported marketing action: {action}") from exc

    def create_campaign(self, **campaign_data: Any) -> MarketingCampaign:
        return self.service.create_campaign(MarketingCampaign(**campaign_data))

    def update_campaign(self, campaign_id: str, **changes: Any) -> MarketingCampaign:
        return self.service.update_campaign(campaign_id, **changes)

    def pause_campaign(self, campaign_id: str) -> MarketingCampaign:
        return self.update_campaign(campaign_id, status="paused")

    def resume_campaign(self, campaign_id: str) -> MarketingCampaign:
        return self.update_campaign(campaign_id, status="active")

    def duplicate_campaign(self, campaign_id: str, name: str | None = None) -> MarketingCampaign:
        original = self.service.get_campaign(campaign_id)
        duplicate = original.model_copy(update={"id": __import__("uuid").uuid4().hex, "name": name or f"{original.name} (copy)", "status": "draft", "spend": 0.0, "revenue": 0.0})
        return self.service.create_campaign(duplicate)

    def archive_campaign(self, campaign_id: str) -> MarketingCampaign:
        return self.update_campaign(campaign_id, status="archived")
