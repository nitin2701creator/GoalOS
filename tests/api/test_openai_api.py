"""API tests for the LibreChat-compatible GoalOS interface.

Proves the required production flow: LibreChat-compatible request →
``/v1/chat/completions`` → GoalOS agent factory → skill/integration
resolution → workflow execution → persisted results → OpenAI-format
response. External services run through the shared fake HTTP transport;
nothing is fabricated and no Aider is required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.main import app
from tests.integration_helpers import FakeResponse, FakeUrlOpener

API_KEY = "goalos-test-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}

CREATE_SEO_AGENT = "Create an agent capable of analyzing Organigram website SEO."
RUN_SEO_ANALYSIS = (
    "Run the website SEO analysis for Organigram at https://www.organigram.com."
)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with an isolated DB and the API key configured."""
    monkeypatch.setenv("GOALOS_API_KEY", API_KEY)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'openai_e2e.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _chat(client: TestClient, messages: list[dict], *, stream: bool = False, headers=None):
    """POST a chat completion request with the configured API key."""
    return client.post(
        "/v1/chat/completions",
        json={"model": "goalos-autonomous", "messages": messages, "stream": stream},
        headers=headers if headers is not None else AUTH,
    )


def test_models_endpoint_returns_openai_format(api) -> None:
    """GET /v1/models returns a valid OpenAI models-list response."""
    response = api.get("/v1/models", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert len(body["data"]) == 1
    model = body["data"][0]
    assert model["id"] == "goalos-autonomous"
    assert model["object"] == "model"
    assert model["owned_by"] == "goalos"


def test_auth_rejects_invalid_key(api) -> None:
    """A wrong bearer token is rejected with 401."""
    response = api.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
    assert response.status_code == 401
    assert "invalid API key" in response.json()["detail"]

    chat = _chat(api, [{"role": "user", "content": CREATE_SEO_AGENT}],
                 headers={"Authorization": "Bearer wrong-key"})
    assert chat.status_code == 401


def test_auth_required_when_key_missing(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without GOALOS_API_KEY the API refuses to serve /v1."""
    monkeypatch.delenv("GOALOS_API_KEY", raising=False)
    monkeypatch.delenv("GOALOS_OPENWEBUI_API_KEY", raising=False)
    response = api.get("/v1/models", headers=AUTH)
    assert response.status_code == 503
    assert "GOALOS_API_KEY" in response.json()["detail"]

    chat = _chat(api, [{"role": "user", "content": CREATE_SEO_AGENT}])
    assert chat.status_code == 503


def test_chat_completions_openai_response_shape(api) -> None:
    """POST /v1/chat/completions returns valid OpenAI-compatible JSON."""
    response = _chat(api, [{"role": "user", "content": CREATE_SEO_AGENT}])
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "goalos-autonomous"
    assert body["id"].startswith("chatcmpl-")
    assert body["usage"]["total_tokens"] == 0
    choice = body["choices"][0]
    assert choice["index"] == 0
    assert choice["message"]["role"] == "assistant"
    assert isinstance(choice["message"]["content"], str)
    assert choice["finish_reason"] == "stop"


def test_chat_creates_agent_through_factory(api) -> None:
    """\"Create an agent...\" resolves capabilities, skills, and integrations."""
    response = _chat(api, [{"role": "user", "content": CREATE_SEO_AGENT}])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "Keyword Research Agent" in content
    assert "ACTIVE" in content
    assert "keyword_research" in content
    assert "website_analysis" in content

    agents = api.get("/api/v1/agents", headers=AUTH)
    assert agents.status_code == 200
    agents_body = agents.json()
    assert len(agents_body) == 1
    agent = agents_body[0]
    assert agent["name"] == "Keyword Research Agent"
    assert agent["status"] == "ACTIVE"
    assert set(agent["capabilities"]) == {
        "keyword_research",
        "website_analysis",
        "content_analysis",
    }
    assert set(agent["skills"]) == {
        "keyword_research",
        "website_analysis",
        "content_analysis",
    }
    # web + website integrations resolved from the capability catalog.
    assert "web" in agent["integrations"]
    assert "website" in agent["integrations"]


def test_chat_runs_workflow_and_persists(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """\"Run the SEO analysis\" executes the real pipeline and persists it.

    The search provider is configured and the transport faked, so the REAL
    web fetch/crawl/search pipelines run hermetically.
    """
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    response = _chat(api, [{"role": "user", "content": RUN_SEO_ANALYSIS}])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    # Deterministic result — never the LLM placeholder without a key.
    assert "free-llm-provider-ready" not in content
    assert "Completed" in content
    assert "keyword_research: Completed" in content
    assert "website_analysis: Completed" in content

    # The goal → project → workflow chain is persisted and queryable.
    workflows = api.get("/api/v1/workflows", headers=AUTH).json()
    completed = [w for w in workflows if w["status"] == "Completed"]
    assert len(completed) == 1
    run = completed[0]
    assert run["evaluation"]["passed"] is True
    assert run["evaluation"]["completed_steps"] == 2
    capabilities = [step["capability"] for step in run["steps"]]
    assert capabilities == ["keyword_research", "website_analysis"]
    assert all(step["status"] == "Completed" for step in run["steps"])
    # The keyword step came from the real search pipeline.
    assert run["results"]["keyword_research"]["source"] == "web.search"
    # The website step came from the real crawl pipeline.
    assert run["results"]["website_analysis"]["source"] == "website.crawl"

    goals = api.get("/api/v1/goals", headers=AUTH).json()
    assert any("SEO analysis" in goal["title"] for goal in goals)


def test_chat_reports_integration_not_configured_honestly(api) -> None:
    """Without a search provider the run reports INTEGRATION_NOT_CONFIGURED.

    No provider is configured, so ``web.search`` is unavailable; GoalOS
    must report the missing configuration instead of inventing results.
    """
    response = _chat(api, [{"role": "user", "content": RUN_SEO_ANALYSIS}])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content.startswith("INTEGRATION_NOT_CONFIGURED")
    assert "web.search" in content

    workflows = api.get("/api/v1/workflows", headers=AUTH).json()
    failed = [w for w in workflows if w["status"] == "Failed"]
    assert len(failed) == 1
    assert "web.search" in (failed[0]["error_message"] or "")
    assert failed[0]["evaluation"]["passed"] is False


def test_chat_refuses_dangerous_actions(api) -> None:
    """Chat never auto-authorizes dangerous permissions."""
    # Agent creation requiring SEND_EMAIL is refused, no agent is created.
    response = _chat(
        api,
        [{"role": "user", "content": "Create an agent that drafts and sends outreach emails."}],
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "will not auto-authorize dangerous actions" in content
    assert "SEND_EMAIL" in content
    assert api.get("/api/v1/agents", headers=AUTH).json() == []

    # Workflow execution requiring EXECUTE_CODE is refused as well.
    response = _chat(api, [{"role": "user", "content": "Calculate the sum of 40 and 2."}])
    content = response.json()["choices"][0]["message"]["content"]
    assert "will not auto-authorize dangerous actions" in content
    assert "EXECUTE_CODE" in content
    assert api.get("/api/v1/workflows", headers=AUTH).json() == []


def test_chat_streaming_returns_sse(api) -> None:
    """stream=true returns a single-chunk server-sent event stream."""
    response = _chat(
        api,
        [{"role": "user", "content": CREATE_SEO_AGENT}],
        stream=True,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    lines = [line for line in response.text.splitlines() if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    payloads = [json.loads(line[6:]) for line in lines if line != "data: [DONE]"]
    assert payloads[0]["object"] == "chat.completion.chunk"
    delta = payloads[0]["choices"][0]["delta"]
    assert delta["role"] == "assistant"
    assert "Keyword Research Agent" in delta["content"]
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"


def test_conversation_context_preserved(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prior conversation turns are carried into the persisted workflow."""
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    response = _chat(
        api,
        [
            {"role": "user", "content": "We need to improve Organigram's organic visibility."},
            {"role": "assistant", "content": "Understood. I can research keywords and analyze the website."},
            {"role": "user", "content": "Run the SEO analysis now."},
        ],
    )
    assert response.status_code == 200
    assert "Completed" in response.json()["choices"][0]["message"]["content"]

    workflows = api.get("/api/v1/workflows", headers=AUTH).json()
    requirement = workflows[0]["requirement"]
    assert "Understood. I can research keywords and analyze the website." in requirement
    assert "Current request: Run the SEO analysis now." in requirement


def test_llm_provider_polishes_when_configured(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured LLM provider summarizes the result; none returns deterministic text."""
    class FakeProvider:
        api_key = "fake-key"

        def request(self, prompt: str, **kwargs):
            return {"response": "Polished summary by the configured LLM."}

        def health_check(self) -> bool:
            return True

    class FakeProviderFactory:
        @staticmethod
        def create():
            return FakeProvider()

    monkeypatch.setattr("app.api.v1.openai.ProviderFactory", FakeProviderFactory)
    response = _chat(api, [{"role": "user", "content": CREATE_SEO_AGENT}])
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "Polished summary by the configured LLM."


def test_health_endpoints_structured(api) -> None:
    """/health and /v1/health report structured status without secrets."""
    public = api.get("/health")
    assert public.status_code == 200
    body = public.json()
    assert body["status"] == "ok"
    assert body["goalos"]["status"] == "running"
    assert body["database"]["status"] == "healthy"
    assert "provider" in body["llm"]
    assert body["integrations"]["total"] > 0

    secured = api.get("/v1/health", headers=AUTH)
    assert secured.status_code == 200
    assert secured.json() == body

    # No credential values leak into the health payload.
    serialized = json.dumps(body)
    for secret in ("goalos-test-key", "consumer_secret", "PRIVATE KEY", "Bearer"):
        assert secret not in serialized


def test_sales_analysis_with_woocommerce_and_ga4(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """\"Analyze Organigram sales\" resolves WooCommerce + GA4 integrations.

    The store and analytics backends are configured and served by the fake
    transport, so the real WooCommerce/GA4 request pipelines run hermetically.
    """
    monkeypatch.setenv("GOALOS_WOO_URL", "https://shop.organigram.example")
    monkeypatch.setenv("GOALOS_WOO_CONSUMER_KEY", "ck_test")
    monkeypatch.setenv("GOALOS_WOO_CONSUMER_SECRET", "cs_test")
    monkeypatch.setenv("GOALOS_GA4_PROPERTY_ID", "123456789")

    class FakeTokenProvider:
        def get_token(self) -> str:
            return "fake-token"

    monkeypatch.setattr(
        "app.integrations.google_analytics.GoogleAnalyticsConnector._default_token_provider",
        lambda self: FakeTokenProvider(),
    )

    sites = {
        "https://shop.organigram.example/wp-json/wc/v3/products": (
            json.dumps(
                [
                    {"id": 1, "name": "Organigram Chocolate Bar", "stock_quantity": 12, "stock_status": "instock"},
                    {"id": 2, "name": "Organigram Vape Cartridge", "stock_quantity": 3, "stock_status": "instock"},
                ]
            ).encode(),
            "application/json",
        ),
        "https://analyticsdata.googleapis.com/v1beta/properties/123456789:runReport": (
            json.dumps(
                {
                    "dimensionHeaders": [{"name": "date"}],
                    "metricHeaders": [{"name": "sessions"}, {"name": "totalUsers"}],
                    "rows": [
                        {
                            "dimensionValues": [{"value": "20260701"}],
                            "metricValues": [{"value": "1200"}, {"value": "340"}],
                        }
                    ],
                }
            ).encode(),
            "application/json",
        ),
    }

    class SalesOpener(FakeUrlOpener):
        def __call__(self, request, timeout=None):
            url = str(getattr(request, "full_url", request))
            base = url.split("?", 1)[0]
            for site_url, (body, content_type) in self.sites.items():
                if base.rstrip("/") == site_url.rstrip("/"):
                    return FakeResponse(body, url, content_type=content_type)
            return FakeResponse(b"Not Found", url, status=404)

    monkeypatch.setattr("app.integrations.http_client.urlopen", SalesOpener(sites=sites))

    response = _chat(
        api,
        [{"role": "user", "content": "Analyze Organigram sales for the e-commerce store."}],
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "Completed" in content
    assert "sales_analysis: Completed" in content

    workflows = api.get("/api/v1/workflows", headers=AUTH).json()
    run = workflows[0]
    assert run["status"] == "Completed"
    assert run["results"]["sales_analysis"]["source"] == "woocommerce.products"
    assert "Organigram Chocolate Bar" in run["results"]["sales_analysis"]["products"]
    assert run["results"]["sales_analysis"]["analytics"]["row_count"] == 1
    assert run["results"]["sales_analysis"]["analytics"]["rows"][0]["sessions"] == "1200"


ONLY_WEB_RESEARCH_GOAL = (
    "Use ONLY the web_research capability. Do not use WooCommerce, analytics, "
    "website_analysis, or any other integration. Search the web for Organigram "
    "India organic food and return the top 3 search results with their titles "
    "and URLs."
)


def test_explicit_restriction_controls_resolution(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """"ONLY web_research ... do not use other integrations" yields a single step.

    This is the production bug regression: the autonomous planner must not
    add sales_analysis / woocommerce / analytics capabilities merely because
    the prohibition text mentions them.
    """
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    response = _chat(api, [{"role": "user", "content": ONLY_WEB_RESEARCH_GOAL}])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "Completed" in content
    assert "INTEGRATION_NOT_CONFIGURED" not in content
    assert "web_research: Completed" in content

    workflows = api.get("/api/v1/workflows", headers=AUTH).json()
    assert len(workflows) == 1
    run = workflows[0]
    assert run["status"] == "Completed"
    # The workflow contains ONLY the web_research capability.
    assert [step["capability"] for step in run["steps"]] == ["web_research"]
    assert all(step["status"] == "Completed" for step in run["steps"])
    assert run["results"]["web_research"]["source"] == "web.search"
    # No prohibited capabilities were resolved or executed.
    resolved = set(run["resolved_capabilities"])
    assert "sales_analysis" not in resolved
    assert "woocommerce_read" not in resolved
    assert "google_analytics_read" not in resolved
    assert "website_analysis" not in resolved
    assert "website_crawl" not in resolved
    assert run["evaluation"]["passed"] is True
    assert run["evaluation"]["completed_steps"] == 1


def test_restriction_still_reports_required_unavailable_integration(
    api,
) -> None:
    """A genuinely required unavailable capability still reports honestly."""
    # No search provider configured: web_research requires web.search, so
    # the run must fail with INTEGRATION_NOT_CONFIGURED — not fabricate
    # results, and not silently add other capabilities.
    response = _chat(api, [{"role": "user", "content": ONLY_WEB_RESEARCH_GOAL}])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content.startswith("INTEGRATION_NOT_CONFIGURED")
    assert "web.search" in content

    workflows = api.get("/api/v1/workflows", headers=AUTH).json()
    failed = [w for w in workflows if w["status"] == "Failed"]
    assert len(failed) == 1
    assert [step["capability"] for step in failed[0]["steps"]] == ["web_research"]
    assert "web.search" in (failed[0]["error_message"] or "")
    assert "woocommerce" not in (failed[0]["error_message"] or "")


class PlanFakeProvider:
    """Fake LLM provider: returns a goal plan only for the planning prompt."""

    api_key = "fake-key"

    def __init__(self, plan_content: str) -> None:
        self.plan_content = plan_content

    def request(self, prompt: str, **kwargs):  # test double
        if "GoalOS goal planning engine" in prompt:
            return {"choices": [{"message": {"content": self.plan_content}}]}
        # Every other LLM call (refine/polish) returns unparseable text so
        # the deterministic paths stay untouched.
        return {"response": "no JSON here."}

    def health_check(self) -> bool:
        return True


class PlanFakeProviderFactory:
    @staticmethod
    def create():
        return PlanFakeProvider(_SEO_PLAN_JSON)


_SEO_PLAN_JSON = (
    '{"steps": ['
    '{"capability": "web_research", "goal": "Research Organigram SEO issues first"},'
    '{"capability": "website_analysis", "goal": "Analyze the site using the research"}'
    "]}"
)


def test_chat_multi_step_goal_plan_executes_in_order_with_chaining(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An LLM goal plan drives ordered, result-chained execution end to end.

    "Analyze Organigram's SEO" with a configured LLM produces the ordered
    plan [web_research → website_analysis]; the workflow executes the steps
    in that order and the second step receives the first step's output.
    """
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())
    monkeypatch.setattr("app.api.v1.openai.ProviderFactory", PlanFakeProviderFactory)

    response = _chat(api, [{"role": "user", "content": RUN_SEO_ANALYSIS}])
    assert response.status_code == 200

    workflows = api.get("/api/v1/workflows", headers=AUTH).json()
    run = next(w for w in workflows if w["status"] == "Completed")
    # The plan order (not the catalog order) is the execution order.
    assert [step["capability"] for step in run["steps"]] == [
        "web_research",
        "website_analysis",
    ]
    assert all(step["status"] == "Completed" for step in run["steps"])
    assert run["plan"] is not None
    assert [step["capability"] for step in run["plan"]] == [
        "web_research",
        "website_analysis",
    ]
    assert run["results"]["web_research"]["source"] == "web.search"
    assert run["results"]["website_analysis"]["source"] == "website.crawl"

    # The second step's persisted execution input contains the chained
    # output of the first step (previous_outputs).
    executions = api.get("/api/v1/executions/runtime", headers=AUTH).json()
    by_capability = {item["capability"]: item for item in executions}
    previous = (by_capability["website_analysis"]["input"] or {}).get(
        "previous_outputs"
    ) or {}
    assert "web_research" in previous
    assert previous["web_research"]["source"] == "web.search"
    assert by_capability["web_research"]["input"]["previous_outputs"] == {}


def test_chat_llm_plan_never_adds_prohibited_capabilities(api, monkeypatch) -> None:
    """A misbehaving LLM plan cannot add capabilities the user prohibited.

    With "ONLY web_research ... do not use other integrations", the LLM
    plan suggests sales_analysis and website_analysis alongside
    web_research — the final plan and the executed workflow contain only
    web_research.
    """
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    bad_plan = (
        '{"steps": ['
        '{"capability": "web_research", "goal": "Search"},'
        '{"capability": "sales_analysis", "goal": "Should never run"},'
        '{"capability": "website_analysis", "goal": "Should never run"}'
        "]}"
    )

    class BadPlanFactory:
        @staticmethod
        def create():
            return PlanFakeProvider(bad_plan)

    monkeypatch.setattr("app.api.v1.openai.ProviderFactory", BadPlanFactory)

    response = _chat(api, [{"role": "user", "content": ONLY_WEB_RESEARCH_GOAL}])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "INTEGRATION_NOT_CONFIGURED" not in content

    workflows = api.get("/api/v1/workflows", headers=AUTH).json()
    run = next(w for w in workflows if w["status"] == "Completed")
    assert [step["capability"] for step in run["steps"]] == ["web_research"]
    assert "sales_analysis" not in (run["results"] or {})
    assert "website_analysis" not in (run["results"] or {})
    assert [step["capability"] for step in run["plan"]] == ["web_research"]

    executions = api.get("/api/v1/executions/runtime", headers=AUTH).json()
    assert {item["capability"] for item in executions} == {"web_research"}


def test_works_without_aider(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """GoalOS runs the full chat flow with no Aider anywhere in the process."""
    assert "aider" not in sys.modules
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    response = _chat(api, [{"role": "user", "content": RUN_SEO_ANALYSIS}])
    assert response.status_code == 200
    assert "aider" not in sys.modules
