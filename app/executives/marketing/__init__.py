"""Marketing executive foundation."""

from .campaign_planner import CampaignPlanner
from .marketing_executive import MarketingExecutive
from .marketing_models import AudienceSegment, BudgetPlan, CampaignRecommendation, CreativeAsset, MarketingCampaign, MarketingKPI, MarketingSummary
from .marketing_service import MarketingService

__all__ = ["AudienceSegment", "BudgetPlan", "CampaignPlanner", "CampaignRecommendation", "CreativeAsset", "MarketingCampaign", "MarketingExecutive", "MarketingKPI", "MarketingService", "MarketingSummary"]
