"""Purchase Order Intelligence Service.

Provides a thin wrapper around the configured LLM endpoint to assess the
risk level of a purchase order.  The service is deliberately lightweight
so that it can be used both from API handlers and from command‑line tools
without pulling in heavy dependencies.

Typical usage:

    from app.ai.purchase_order.intelligence_service import PurchaseOrderIntelligenceService
    service = PurchaseOrderIntelligenceService()
    risk = service.assess_risk({"order_id": "PO‑123", "amount": 15000, "vendor": "Acme Ltd."})
    print(risk)   # -> "Low" | "Medium" | "High"
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import requests

from app.ai.config import LLMConfig


@dataclass(frozen=True, slots=True)
class PurchaseOrderRiskResult:
    """Result returned by :meth:`PurchaseOrderIntelligenceService.assess_risk`.

    Attributes
    ----------
    risk_level:
        One of ``"Low"``, ``"Medium"``, or ``"High"``.
    raw_response:
        The full JSON payload returned by the LLM endpoint – useful for
        debugging or logging.
    """

    risk_level: str
    raw_response: Mapping[str, Any]


class PurchaseOrderIntelligenceService:
    """Service that asks the LLM to evaluate purchase‑order risk."""

    _VALID_RISK_LEVELS = {"Low", "Medium", "High"}

    def __init__(self, config: LLMConfig | None = None) -> None:
        """Create a new service instance.

        Parameters
        ----------
        config:
            Optional explicit configuration.  If omitted the configuration
            is built from the environment via :meth:`LLMConfig.from_env`.
        """
        self._config = config or LLMConfig.from_env()

    def assess_risk(self, purchase_order: Mapping[str, Any]) -> PurchaseOrderRiskResult:
        """Ask the LLM to assess the risk of *purchase_order*.

        The method builds a short prompt containing the order details,
        sends it to the LLM endpoint and parses the response.

        Returns
        -------
        PurchaseOrderRiskResult
            The parsed risk level together with the raw LLM response.

        Raises
        ------
        ValueError
            If the LLM returns a value that is not one of the expected
            risk levels.
        requests.HTTPError
            Propagated if the HTTP request fails.
        """
        prompt = self._build_prompt(purchase_order)

        # Prepare request payload – the exact schema depends on the LLM provider.
        payload = {
            "model": self._config.default_model,
            "prompt": prompt,
            "max_tokens": 10,
        }

        headers = {}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        headers["Content-Type"] = "application/json"

        response = requests.post(
            f"{self._config.base_url.rstrip('/')}/v1/completions",
            data=json.dumps(payload),
            headers=headers,
            timeout=self._config.timeout,
        )
        response.raise_for_status()
        raw = response.json()

        # The provider is expected to return a structure similar to:
        # {"choices": [{"text": "Medium"}]}
        try:
            risk_text = raw["choices"][0]["text"].strip()
        except (KeyError, IndexError, AttributeError) as exc:
            raise ValueError("Malformed LLM response – missing risk text") from exc

        if risk_text not in self._VALID_RISK_LEVELS:
            raise ValueError(f"Unexpected risk level returned by LLM: {risk_text!r}")

        return PurchaseOrderRiskResult(risk_level=risk_text, raw_response=raw)

    @staticmethod
    def _build_prompt(purchase_order: Mapping[str, Any]) -> str:
        """Create a concise prompt for the LLM.

        The prompt is deliberately short – it lists the most relevant fields
        and asks the model to output only the risk level.

        Example output from the LLM should be exactly one of:
        ``Low``, ``Medium`` or ``High``.
        """
        # Convert the mapping to a JSON‑like string for readability.
        po_repr = json.dumps(purchase_order, ensure_ascii=False)
        return (
            "You are an expert financial analyst. "
            "Given the following purchase order data, assess the risk level "
            "and respond with only one word: Low, Medium, or High.\n"
            f"{po_repr}"
        )
