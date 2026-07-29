"""Unit tests for :class:`app.ai.purchase_order.intelligence_service.PurchaseOrderIntelligenceService`."""

from __future__ import annotations

import json
import requests
from unittest.mock import Mock, patch

import pytest

from app.ai.config import LLMConfig
from app.ai.purchase_order.intelligence_service import (
    PurchaseOrderIntelligenceService,
    PurchaseOrderRiskResult,
)


@pytest.fixture
def dummy_config() -> LLMConfig:
    """A deterministic configuration that points to a dummy endpoint."""
    return LLMConfig(
        base_url="http://dummy-llm.local",
        api_key="dummy-key",
        timeout=1.0,
        default_model="dummy-model",
        max_retries=0,
    )


def test_assess_risk_returns_expected_result(dummy_config: LLMConfig) -> None:
    """Happy‑path: the LLM returns a recognised risk level."""
    sample_po = {"order_id": "PO-001", "amount": 12000, "vendor": "Acme Corp"}

    # Mock the HTTP response from ``requests.post``.
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{"text": "Medium"}],
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        service = PurchaseOrderIntelligenceService(config=dummy_config)
        result: PurchaseOrderRiskResult = service.assess_risk(sample_po)

    # Verify that the request payload contains our prompt.
    called_args, called_kwargs = mock_post.call_args
    assert called_args[0] == f"{dummy_config.base_url}/v1/completions"
    payload = json.loads(called_kwargs["data"])
    assert payload["model"] == dummy_config.default_model
    assert "Acme Corp" in payload["prompt"]

    # Validate the returned dataclass.
    assert isinstance(result, PurchaseOrderRiskResult)
    assert result.risk_level == "Medium"
    assert result.raw_response["choices"][0]["text"] == "Medium"


def test_assess_risk_raises_on_unexpected_risk(dummy_config: LLMConfig) -> None:
    """The service should raise ``ValueError`` if the LLM returns an unknown token."""
    sample_po = {"order_id": "PO-002", "amount": 5000, "vendor": "Beta Ltd"}

    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{"text": "VeryHigh"}],
    }

    with patch("requests.post", return_value=mock_response):
        service = PurchaseOrderIntelligenceService(config=dummy_config)
        with pytest.raises(ValueError, match="Unexpected risk level"):
            service.assess_risk(sample_po)


def test_assess_risk_propagates_http_error(dummy_config: LLMConfig) -> None:
    """If the HTTP request fails, the original ``HTTPError`` should bubble up."""
    sample_po = {"order_id": "PO-003", "amount": 8000, "vendor": "Gamma Inc"}

    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("Bad request")

    with patch("requests.post", return_value=mock_response):
        service = PurchaseOrderIntelligenceService(config=dummy_config)
        with pytest.raises(requests.HTTPError):
            service.assess_risk(sample_po)
