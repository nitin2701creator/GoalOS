from datetime import date

import pytest

from app.executives.marketing import CampaignPlanner, MarketingExecutive


def test_lifecycle_summary_kpis_and_integrations():
    executive = MarketingExecutive()
    assert not executive.health_check()
    executive.initialize()
    assert executive.health_check()
    campaign = executive.create_campaign(name="Launch", objective="sales", channel="Meta Ads", budget=1000, spend=100, revenue=350)
    summary = executive.get_summary()
    assert summary.campaign_count == 1
    assert summary.active_campaign_count == 0
    assert {kpi.name for kpi in executive.get_kpis()} == {"ROAS", "CAC", "CTR", "CPC", "CPM", "Conversion Rate"}
    assert next(k for k in executive.get_kpis() if k.name == "ROAS").value == 3.5
    assert "Google Analytics 4" in executive.supported_integrations()
    executive.shutdown()
    assert not executive.health_check()
    assert campaign.status == "draft"


def test_campaign_execution_commands_and_validation():
    executive = MarketingExecutive()
    campaign = executive.execute("create_campaign", name="Summer", objective="awareness", channel="Instagram")
    assert executive.execute("resume_campaign", campaign_id=campaign.id).status == "active"
    assert executive.execute("pause_campaign", campaign_id=campaign.id).status == "paused"
    copied = executive.execute("duplicate_campaign", campaign_id=campaign.id)
    assert copied.id != campaign.id and copied.status == "draft"
    assert executive.execute("archive_campaign", campaign_id=campaign.id).status == "archived"
    with pytest.raises(ValueError, match="Unsupported"):
        executive.execute("publish_campaign")


def test_planner_covers_all_required_planning_capabilities():
    planner = CampaignPlanner()
    assert planner.campaign_plan("Launch", "sales", "Meta Ads").channel == "Meta Ads"
    assert planner.audience_plan("Buyers", "Recent visitors", country="IN").criteria == {"country": "IN"}
    assert planner.budget_plan(700, days=7).daily_budget == 100
    assert planner.creative_plan("Hero", "image").asset_type == "image"
    assert planner.ab_test_plan("Shorter CTA wins", "Buy now", "Shop now")["primary_metric"] == "Conversion Rate"
    calendar = planner.weekly_content_calendar(date(2026, 1, 5))
    assert len(calendar) == 7 and calendar[0]["date"] == date(2026, 1, 5)


def test_executive_exposes_planning_and_monitoring_helpers():
    executive = MarketingExecutive()
    campaign = executive.create_campaign(name="Performance", objective="sales", channel="Google Ads", spend=50, revenue=125)
    assert executive.plan_campaign("Next", "leads", "LinkedIn").status == "draft"
    assert len(executive.plan_weekly_content_calendar(date(2026, 1, 5))) == 7
    assert executive.monitor_roas() == 2.5
    assert executive.monitor_cac() == executive.monitor_ctr() == executive.monitor_cpc() == executive.monitor_cpm() == executive.monitor_conversion_rate() == 0
    assert campaign.name == "Performance"
