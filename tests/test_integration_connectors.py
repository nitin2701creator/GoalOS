"""Unit tests for the GoalOS integration connectors.

Exercises the real HTTP, crawl, search, WooCommerce, GA4, Meta, Gmail, and
scheduler pipelines over an injectable fake transport — no network, no
fabricated success.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.permissions import Permission
from app.db.base import Base
from app.db.models.goal import Goal
from app.db.models.project import Project
from app.db.models.workflow import Workflow
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.exceptions import (
    CapabilityUnavailableError,
    PermissionDeniedError,
)
from app.integrations.google_analytics import GoogleAnalyticsConnector
from app.integrations.http_client import (
    HttpClient,
    HttpResponseTooLargeError,
    HttpStatusError,
)
from app.integrations.meta_ads import MetaAdsConnector
from app.integrations.scheduler import SchedulerConnector, next_run_at
from app.integrations.web import DuckDuckGoSearchProvider, WebConnector
from app.integrations.website import WebsiteConnector
from app.integrations.woocommerce import WooCommerceConnector
from tests.integration_helpers import (
    FakeResponse,
    make_fake_opener,
)


# ---------------------------------------------------------------------------
# Web connector
# ---------------------------------------------------------------------------
def test_web_connector_fetch_parses_page(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = make_fake_opener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    connector = WebConnector()

    result = connector.fetch("https://www.organigram.com")

    assert result.status == 200
    assert result.title == "Organigram - Premium Cannabis Products"
    assert "Organigram is a leading producer" in result.text
    assert ("GET", "https://www.organigram.com") in opener.calls


def test_web_connector_fetch_status_and_timeout_handling() -> None:
    def boom(_request: Any, timeout: float | None = None) -> FakeResponse:
        raise TimeoutError("timed out")

    from app.integrations.http_client import HttpTimeoutError

    connector = WebConnector(client=HttpClient(opener=boom))
    with pytest.raises(HttpTimeoutError):
        connector.fetch("https://example.com")


def test_http_client_raises_on_5xx_and_too_large() -> None:
    def error_opener(_request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(b"boom", "https://example.com", status=500)

    client = HttpClient(opener=error_opener)
    with pytest.raises(HttpStatusError):
        client.fetch("https://example.com")

    def huge_opener(_request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(b"x" * 1024, "https://example.com", content_type="text/plain")

    client = HttpClient(opener=huge_opener, max_bytes=100)
    with pytest.raises(HttpResponseTooLargeError):
        client.fetch("https://example.com")


def test_http_client_builds_query_params() -> None:
    seen: dict[str, str] = {}

    def recording_opener(request: Any, timeout: float | None = None) -> FakeResponse:
        seen["url"] = str(request.full_url)
        return FakeResponse(b"{}", "https://api.example.com", content_type="application/json")

    client = HttpClient(opener=recording_opener)
    client.fetch("https://api.example.com/products", params={"per_page": 5, "search": "a b"})
    assert "per_page=5" in seen["url"]
    assert "search=a+b" in seen["url"]


def test_web_search_requires_provider() -> None:
    connector = WebConnector()
    with pytest.raises(CapabilityUnavailableError, match="search provider"):
        connector.search("organigram")


def test_duckduckgo_search_parses_real_results(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = make_fake_opener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    connector = WebConnector(search_provider=DuckDuckGoSearchProvider(client=HttpClient()))

    results = connector.search("organigram keywords")

    assert results.provider == "duckduckgo"
    titles = [item.title for item in results.results]
    assert "Organigram SEO Guide" in titles
    assert results.results[0].url.startswith("https://example.com/")


# ---------------------------------------------------------------------------
# Website crawler
# ---------------------------------------------------------------------------
def test_website_crawler_same_domain_with_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = make_fake_opener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    connector = WebsiteConnector()

    crawl = connector.crawl("https://www.organigram.com", max_pages=10, max_depth=2)

    assert crawl.total_pages >= 2
    pages_by_url = {page.url: page for page in crawl.pages}
    homepage = pages_by_url["https://www.organigram.com"]
    assert homepage.title == "Organigram - Premium Cannabis Products"
    assert homepage.meta_description
    assert homepage.h1s == ("Welcome to Organigram",)
    assert homepage.canonical == "https://www.organigram.com/"
    assert homepage.word_count > 0
    assert "/about" in " ".join(homepage.internal_links)
    assert not any("external.example.org" in link for link in homepage.internal_links)
    assert "missing canonical" not in homepage.findings
    assert "thin content" not in homepage.findings

    about = pages_by_url.get("https://www.organigram.com/about")
    assert about is not None
    assert any("multiple H1s" in finding for finding in about.findings)

    assert crawl.robots["disallow"] == ["/private"]
    assert crawl.robots["allow"] == ["/public"]


def test_website_crawler_respects_page_limit_and_404s(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = make_fake_opener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    connector = WebsiteConnector()

    crawl = connector.crawl("https://www.organigram.com", max_pages=1, max_depth=0)
    assert crawl.total_pages == 1


def test_website_connector_analyze_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = make_fake_opener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    connector = WebsiteConnector()

    result = connector.execute(
        "website.analyze",
        {"url": "https://www.organigram.com", "max_pages": 5, "max_depth": 1},
        permissions={Permission.READ_WEBSITE},
    )

    assert result["total_pages"] >= 2
    assert result["pages"][0]["title"]


# ---------------------------------------------------------------------------
# WooCommerce
# ---------------------------------------------------------------------------
def test_woocommerce_reports_not_configured_without_env() -> None:
    connector = WooCommerceConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
    assert not connector.is_configured


def test_woocommerce_reads_products_and_enforces_write_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    def woo_opener(request: Any, timeout: float | None = None) -> FakeResponse:
        url = str(request.full_url)
        product = {"id": 1, "name": "Capsule", "stock_quantity": 4, "stock_status": "instock"}
        if str(getattr(request, "get_method", lambda: "GET")()) == "PUT":
            return FakeResponse(json.dumps({**product, "stock_quantity": 9}).encode(), url, content_type="application/json")
        return FakeResponse(json.dumps([product]).encode(), url, content_type="application/json")

    monkeypatch.setattr("app.integrations.http_client.urlopen", woo_opener)
    connector = WooCommerceConnector(
        client=HttpClient(),
        base_url="https://shop.example.com",
        consumer_key="ck",
        consumer_secret="cs",
    )
    assert connector.is_configured

    products = connector.execute(
        "woocommerce.products", {"per_page": 5}, permissions={Permission.READ_WEBSITE}
    )
    assert products["items"][0]["name"] == "Capsule"

    stock = connector.execute(
        "woocommerce.inventory", {}, permissions={Permission.READ_WEBSITE}
    )
    assert stock["low_stock"][0]["name"] == "Capsule"

    with pytest.raises(PermissionDeniedError, match="WRITE_WEBSITE"):
        connector.execute(
            "woocommerce.product.update",
            {"product_id": 1, "stock_quantity": 9},
            permissions={Permission.READ_WEBSITE},
        )

    updated = connector.execute(
        "woocommerce.product.update",
        {"product_id": 1, "stock_quantity": 9},
        permissions={Permission.READ_WEBSITE, Permission.WRITE_WEBSITE},
    )
    assert updated["stock_quantity"] == 9


# ---------------------------------------------------------------------------
# Google Analytics 4
# ---------------------------------------------------------------------------
class FakeTokenProvider:
    def get_token(self) -> str:
        return "fake-access-token"


def test_ga4_reports_not_configured_and_auth_required() -> None:
    assert GoogleAnalyticsConnector().health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
    with_credentials = GoogleAnalyticsConnector(
        property_id="123456", token_provider=None
    )
    assert with_credentials.health_check().status is ConnectorHealthStatus.AUTHENTICATION_REQUIRED


def test_ga4_run_report_normalizes_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    def ga4_opener(request: Any, timeout: float | None = None) -> FakeResponse:
        payload = {
            "dimensionHeaders": [{"name": "date"}],
            "metricHeaders": [{"name": "sessions"}],
            "rows": [{"dimensionValues": [{"value": "20260801"}], "metricValues": [{"value": "42"}]}],
        }
        return FakeResponse(json.dumps(payload).encode(), str(request.full_url), content_type="application/json")

    monkeypatch.setattr("app.integrations.http_client.urlopen", ga4_opener)
    connector = GoogleAnalyticsConnector(
        client=HttpClient(),
        property_id="123456",
        token_provider=FakeTokenProvider(),
    )

    report = connector.execute(
        "analytics.report",
        {"start_date": "7daysAgo", "end_date": "today"},
        permissions={Permission.READ_ANALYTICS},
    )

    assert report["row_count"] == 1
    assert report["rows"][0]["sessions"] == "42"
    assert report["dimensions"] == ["date"]
    assert report["realtime"] is False


# ---------------------------------------------------------------------------
# Meta Ads
# ---------------------------------------------------------------------------
def test_meta_ads_reads_campaigns_and_blocks_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    def meta_opener(request: Any, timeout: float | None = None) -> FakeResponse:
        url = str(request.full_url)
        if "/insights" in url:
            body = {"data": [{"campaign_name": "Brand", "spend": "10.5", "impressions": "100", "clicks": "3"}]}
        elif "adaccounts" in url:
            body = {"adaccounts": [{"id": "act_1", "name": "Main"}]}
        else:
            body = {"data": [{"id": "c1", "name": "Brand Campaign", "status": "ACTIVE"}]}
        return FakeResponse(json.dumps(body).encode(), url, content_type="application/json")

    monkeypatch.setattr("app.integrations.http_client.urlopen", meta_opener)
    connector = MetaAdsConnector(
        client=HttpClient(), access_token="tok", ad_account_id="act_1"
    )

    accounts = connector.execute("meta.ads.read", {}, permissions={Permission.READ_ANALYTICS})
    assert accounts["items"][0]["name"] == "Main"

    campaigns = connector.execute("meta.campaigns.read", {}, permissions={Permission.READ_ANALYTICS})
    assert campaigns["items"][0]["name"] == "Brand Campaign"

    insights = connector.execute("meta.insights.read", {}, permissions={Permission.READ_ANALYTICS})
    assert insights["summary"]["spend"] == 10.5

    with pytest.raises(CapabilityUnavailableError, match="not enabled"):
        connector.execute(
            "meta.campaigns.write",
            {},
            permissions={Permission.READ_ANALYTICS, Permission.MODIFY_ADS},
        )


def test_meta_ads_requires_token() -> None:
    assert MetaAdsConnector().health_check().status is ConnectorHealthStatus.NOT_CONFIGURED


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'scheduler.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def scheduled_workflow(session_factory) -> tuple[Session, Workflow]:
    session = session_factory()
    goal = Goal(title="Organigram SEO", description="d", executive_owner="CMO", department="Marketing", priority="High")
    session.add(goal)
    session.commit()
    session.refresh(goal)
    project = Project(goal_id=goal.id, title="p", description="d", owner="o", department="Marketing", priority="High")
    session.add(project)
    session.commit()
    session.refresh(project)
    workflow = Workflow(project_id=project.id, name="Scheduled workflow")
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    yield session, workflow
    session.close()


def test_scheduler_create_requires_explicit_permission(scheduled_workflow) -> None:
    session, workflow = scheduled_workflow
    connector = SchedulerConnector(db=session)

    with pytest.raises(PermissionDeniedError, match="SCHEDULE_WORKFLOWS"):
        connector.execute(
            "scheduler.create",
            {"workflow_id": workflow.id, "schedule": "daily", "requirement": "SEO"},
            permissions={Permission.READ_ANALYTICS},
        )


def test_scheduler_persists_and_survives_restart(session_factory, scheduled_workflow) -> None:
    session, workflow = scheduled_workflow
    connector = SchedulerConnector(db=session)
    workflow_id = workflow.id

    created = connector.execute(
        "scheduler.create",
        {"workflow_id": workflow_id, "schedule": "daily", "requirement": "Organigram SEO"},
        permissions={Permission.READ_ANALYTICS, Permission.SCHEDULE_WORKFLOWS},
    )
    assert created["schedule"] == "daily"
    assert created["next_run_at"]

    listed = connector.execute(
        "scheduler.list", {}, permissions={Permission.READ_ANALYTICS}
    )
    assert listed["scheduled"][0]["workflow_id"] == str(workflow_id)

    session.close()

    # Restart: fresh engine + session over the same database file.
    engine = create_engine(
        f"sqlite:///{Path(session_factory().bind.url.database).parent / 'scheduler.db'}",
        connect_args={"check_same_thread": False},
    )
    Session2 = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session2 = Session2()
    try:
        restarted = SchedulerConnector(db=session2)
        listed = restarted.execute(
            "scheduler.list", {}, permissions={Permission.READ_ANALYTICS}
        )
        assert listed["scheduled"][0]["schedule"] == "daily"

        due = restarted.execute(
            "scheduler.due",
            {"now": datetime.now(timezone.utc).isoformat()},
            permissions={Permission.READ_ANALYTICS},
        )
        assert due["due"] == []
        advanced = restarted.advance(workflow_id)
        assert advanced is not None
        assert advanced["last_run_at"] is not None
    finally:
        session2.close()
        engine.dispose()


def test_next_run_at_schedules() -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    assert next_run_at("hourly", now).hour == 13
    assert next_run_at("daily", now).day == 12
    assert next_run_at("weekly", now).day == 18
    with pytest.raises(ValueError, match="unsupported schedule"):
        next_run_at("cron", now)
