"""Service tests for the GoalOS capability engine.

Covers the persistent registry, resolution (single/many), goal matching
(deterministic + LLM-refined), honest availability, permission gates,
execution through the existing skill/integration runtime, and restart
durability. No fabricated success: unconfigured capabilities report
INTEGRATION_NOT_CONFIGURED.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.permissions import Permission
from app.db.base import Base
from app.integrations.factory import build_default_registry
from app.repositories.capability_repository import CapabilityRepository
from app.schemas.capability import CapabilityCreateRequest
from app.services.capability_service import CapabilityService
from tests.integration_helpers import make_fake_opener

SEO_GOAL = "Analyse Organigram's website SEO and tell me what needs to be fixed."


def _session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'capabilities.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _service(db, *, registry=None, llm_provider=None) -> CapabilityService:
    return CapabilityService(
        CapabilityRepository(db),
        integration_registry=registry or build_default_registry(session=db),
        llm_provider=llm_provider,
    )


def test_register_and_retrieve(tmp_path: Path) -> None:
    factory = _session_factory(tmp_path)
    service = _service(factory())
    request = CapabilityCreateRequest(
        name="test_custom",
        description="A test capability.",
        category="test",
        required_permissions=[Permission.READ_FILES],
        provider_type="native",
        provider="native",
        implementation="calculation",
    )
    created = service.register(request)
    assert created.name == "test_custom"
    assert created.status.value == "ACTIVE"
    assert created.required_permissions == [Permission.READ_FILES]

    retrieved = service.get_by_name("test_custom")
    assert retrieved is not None
    assert retrieved.id == created.id


def test_register_duplicate_is_idempotent(tmp_path: Path) -> None:
    factory = _session_factory(tmp_path)
    service = _service(factory())
    request = CapabilityCreateRequest(
        name="test_custom",
        description="A test capability.",
        provider_type="native",
        provider="native",
        implementation="calculation",
    )
    first = service.register(request)
    second = service.register(request)
    assert second.id == first.id
    assert sum(1 for item in service.list() if item.name == "test_custom") == 1


def test_seed_persists_builtin_catalog(tmp_path: Path) -> None:
    factory = _session_factory(tmp_path)
    service = _service(factory())
    names = {capability.name for capability in service.list()}
    assert "calculation" in names
    assert "seo_audit" in names
    assert "web_search" in names
    assert "website_crawl" in names
    assert "whatsapp_send" in names
    assert "memory_store" in names


def test_resolve_existing_capability(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    resolved = service.resolve("calculation")
    assert resolved.exists is True
    assert resolved.enabled is True
    assert resolved.available is True
    assert resolved.execution_capability == "calculation"
    assert resolved.required_permissions == [Permission.EXECUTE_CODE]


def test_resolve_many(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    resolved = service.resolve_many(["calculation", "seo_audit"])
    assert [item.name for item in resolved] == ["calculation", "seo_audit"]
    assert resolved[1].exists is True
    assert resolved[1].available is True  # website.analyze needs no config


def test_resolve_missing_capability(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    resolved = service.resolve("does_not_exist")
    assert resolved.exists is False
    assert resolved.available is False
    assert resolved.reason == "capability is not registered"


def test_match_goal_identifies_seo_capabilities(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    matched = service.match(SEO_GOAL)
    names = {result.name for result in matched}
    assert "seo_audit" in names
    assert "keyword_research" in names
    assert "website_analysis" in names
    assert all(result.source in ("keyword", "llm") for result in matched)


def test_resolve_for_goal_maps_execution_capabilities(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    resolution = service.resolve_for_goal(SEO_GOAL)
    assert "seo_audit" in resolution.capabilities
    assert "website_crawl" in resolution.capabilities
    # Deduplicated catalog-order execution set drives agent reuse/creation.
    assert resolution.execution_capabilities == ["keyword_research", "website_analysis"]


def test_unavailable_capability_reports_not_configured(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    resolved = service.resolve("whatsapp_send")
    assert resolved.exists is True
    assert resolved.available is False
    assert "INTEGRATION_NOT_CONFIGURED" in (resolved.reason or "")

    result = service.execute("whatsapp_send", {}, {Permission.SEND_WHATSAPP})
    assert result.status == "INTEGRATION_NOT_CONFIGURED"


def test_missing_implementation_reports_not_configured(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    resolved = service.resolve("ocr")
    assert resolved.exists is True
    assert resolved.available is False
    assert "no implementation" in (resolved.reason or "")

    result = service.execute("ocr", {"image": "x"}, {Permission.READ_FILES})
    assert result.status == "INTEGRATION_NOT_CONFIGURED"


def test_insufficient_permissions_denied(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    resolved = service.resolve("calculation", permissions=set())
    assert resolved.permissions_sufficient is False
    assert resolved.missing_permissions == ["EXECUTE_CODE"]

    result = service.execute("calculation", {"a": 1, "b": 2}, set())
    assert result.status == "PERMISSION_DENIED"
    assert "EXECUTE_CODE" in (result.error or "")


def test_execute_calculation_returns_42(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    result = service.execute(
        "calculation",
        {"a": 40, "b": 2},
        {Permission.EXECUTE_CODE},
    )
    assert result.status == "OK"
    assert result.result == {"result": 42.0}


def test_dangerous_write_requires_explicit_authorization(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    # A native capability wired to the calculation skill but requiring
    # SEND_EMAIL: the availability check passes, the permission gate must not.
    request = CapabilityCreateRequest(
        name="test_send",
        description="A write-capability stand-in.",
        required_permissions=[Permission.SEND_EMAIL],
        provider_type="native",
        provider="native",
        implementation="calculation",
    )
    service.register(request)
    denied = service.execute("test_send", {"a": 1, "b": 1}, set())
    assert denied.status == "PERMISSION_DENIED"
    assert "SEND_EMAIL" in (denied.error or "")
    granted = service.execute(
        "test_send", {"a": 1, "b": 1}, {Permission.SEND_EMAIL}
    )
    assert granted.status == "OK"
    assert granted.result == {"result": 2.0}


def test_disable_and_enable(tmp_path: Path) -> None:
    service = _service(_session_factory(tmp_path)())
    service.disable("seo_audit")
    resolved = service.resolve("seo_audit")
    assert resolved.enabled is False
    assert resolved.available is False
    assert resolved.reason == "capability is disabled"
    result = service.execute("seo_audit", {}, {Permission.READ_WEBSITE})
    assert result.status == "DISABLED"
    service.enable("seo_audit")
    assert service.resolve("seo_audit").available is True


def test_skill_capability_requires_search_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = build_default_registry(session=None)
    service = _service(_session_factory(tmp_path)(), registry=registry)
    resolved = service.resolve("keyword_research")
    assert resolved.available is False
    assert "search provider" in (resolved.reason or "")

    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", make_fake_opener())
    configured = _service(
        _session_factory(tmp_path)(),
        registry=build_default_registry(session=None),
    )
    assert configured.resolve("keyword_research").available is True


def test_execute_integration_capability_through_connector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", make_fake_opener())
    service = _service(
        _session_factory(tmp_path)(),
        registry=build_default_registry(session=None),
    )
    result = service.execute(
        "web_search",
        {"query": "organigram", "limit": 3},
        {Permission.READ_WEBSITE},
    )
    assert result.status == "OK"
    assert result.provider == "web"
    assert len(result.result["results"]) >= 2  # real parsed SERP fixtures


def test_llm_refinement_only_accepts_registered_names(tmp_path: Path) -> None:
    class FakeProvider:
        api_key = "fake-key"

        def request(self, prompt: str, **kwargs):
            return {"response": '["web_search", "not_a_capability"]'}

        def health_check(self) -> bool:
            return True

    service = _service(
        _session_factory(tmp_path)(),
        registry=build_default_registry(session=None),
        llm_provider=FakeProvider(),
    )
    # "Distributor discovery" matches nothing with web_search keywords, so the
    # LLM-refined web_search must come back with source "llm" and the unknown
    # name must be discarded.
    matched = service.match("Distributor discovery for Organigram.")
    names = [result.name for result in matched]
    assert "web_search" in names
    assert "not_a_capability" not in names
    llm_sources = [result for result in matched if result.source == "llm"]
    assert any(result.name == "web_search" for result in llm_sources)


def test_restart_durability(tmp_path: Path) -> None:
    factory = _session_factory(tmp_path)
    first = _service(factory())
    first.ensure_seeded()
    first.register(
        CapabilityCreateRequest(
            name="custom_persisted",
            description="Persisted across restart.",
            provider_type="native",
            provider="native",
            implementation="calculation",
        )
    )

    # Fresh composition root over the same database file.
    restarted = _service(factory())
    assert restarted.get_by_name("custom_persisted") is not None
    names = {capability.name for capability in restarted.list()}
    assert "seo_audit" in names
    assert "whatsapp_send" in names
