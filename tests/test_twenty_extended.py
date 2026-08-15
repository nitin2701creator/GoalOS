"""Tests for the extended Twenty CRM connector.

Covers the standard list/get operations (``twenty.list_*`` /
``twenty.get_*``), the ``twenty.health`` capability, and the
``TWENTY_API_URL`` / ``TWENTY_API_KEY`` environment aliases (with the
legacy ``GOALOS_TWENTY_*`` names preserved). Never touches the real
Twenty service.
"""

from __future__ import annotations

import json

import pytest

from app.agents.permissions import Permission
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.exceptions import PermissionDeniedError
from app.integrations.http_client import HttpClient
from app.integrations.twenty import TwentyConnector
from tests.integration_helpers import FakeResponse

PEOPLE_LIST = {
    "data": [
        {"id": "p1", "firstName": "Alice", "lastName": "Doe", "email": "alice@example.com"},
        {"id": "p2", "firstName": "Bob", "lastName": "Smith", "email": "bob@example.com"},
    ],
    "totalCount": 2,
}


def _opener():
    def opener(request, timeout=None) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        method = str(getattr(request, "get_method", lambda: "GET")())
        opener.calls.append((method, url))
        if url.endswith("/rest/people/p1"):
            return FakeResponse(json.dumps({"data": PEOPLE_LIST["data"][0]}).encode(), url, content_type="application/json")
        return FakeResponse(json.dumps(PEOPLE_LIST).encode(), url, content_type="application/json")

    opener.calls = []
    return opener


def _connector(opener, *, base_url: str = "https://api.twenty.test", api_key: str = "test-key") -> TwentyConnector:
    return TwentyConnector(
        client=HttpClient(opener=opener),
        base_url=base_url,
        api_key=api_key,
    )


def test_twenty_list_people() -> None:
    opener = _opener()
    connector = _connector(opener)

    result = connector.execute(
        "twenty.list_people", {"limit": 5}, permissions={Permission.READ_CRM}
    )
    assert result["object"] == "people"
    assert result["total"] == 2
    assert result["items"][0]["email"] == "alice@example.com"
    method, url = opener.calls[0]
    assert method == "GET"
    assert "limit=5" in url


def test_twenty_get_person() -> None:
    opener = _opener()
    connector = _connector(opener)

    result = connector.execute(
        "twenty.get_person", {"id": "p1"}, permissions={Permission.READ_CRM}
    )
    assert result["id"] == "p1"
    assert result["data"]["firstName"] == "Alice"
    _, url = opener.calls[0]
    assert url.endswith("/rest/people/p1")


def test_twenty_get_company_and_opportunity_resolve() -> None:
    opener = _opener()
    connector = _connector(opener)

    company = connector.execute("twenty.get_company", {"id": "p1"}, permissions={Permission.READ_CRM})
    assert company["object"] == "companies"

    opportunity = connector.execute(
        "twenty.list_opportunities", {}, permissions={Permission.READ_CRM}
    )
    assert opportunity["object"] == "opportunities"


def test_twenty_list_requires_read_permission() -> None:
    connector = _connector(_opener())
    with pytest.raises(PermissionDeniedError, match="READ_CRM"):
        connector.execute("twenty.list_people", {}, permissions={Permission.READ_WEBSITE})
    with pytest.raises(PermissionDeniedError, match="READ_CRM"):
        connector.execute("twenty.get_person", {"id": "p1"}, permissions={Permission.READ_WEBSITE})


def test_twenty_health_capability() -> None:
    connector = _connector(_opener())
    result = connector.execute("twenty.health", {}, permissions={Permission.READ_CRM})
    assert result["configured"] is True
    assert result["integration"] == "twenty"


def test_twenty_env_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOALOS_TWENTY_BASE_URL", raising=False)
    monkeypatch.delenv("GOALOS_TWENTY_API_KEY", raising=False)
    monkeypatch.setenv("TWENTY_API_URL", "https://selfhosted.twenty.test")
    monkeypatch.setenv("TWENTY_API_KEY", "alias-key")
    connector = TwentyConnector(client=HttpClient())
    assert connector.is_configured
    assert connector.base_url == "https://selfhosted.twenty.test"
    assert connector.api_key == "alias-key"


def test_twenty_legacy_env_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWENTY_API_URL", raising=False)
    monkeypatch.delenv("TWENTY_API_KEY", raising=False)
    monkeypatch.setenv("GOALOS_TWENTY_BASE_URL", "https://legacy.twenty.test")
    monkeypatch.setenv("GOALOS_TWENTY_API_KEY", "legacy-key")
    connector = TwentyConnector(client=HttpClient())
    assert connector.is_configured
    assert connector.base_url == "https://legacy.twenty.test"


def test_twenty_health_check_still_not_configured_without_any_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWENTY_API_URL", raising=False)
    monkeypatch.delenv("TWENTY_API_KEY", raising=False)
    monkeypatch.delenv("GOALOS_TWENTY_BASE_URL", raising=False)
    monkeypatch.delenv("GOALOS_TWENTY_API_KEY", raising=False)
    connector = TwentyConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
