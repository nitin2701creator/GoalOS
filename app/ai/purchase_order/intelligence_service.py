"""Purchase Order Intelligence Service.

Provides a thin wrapper around the configured LLM endpoint to assess the
risk level of a purchase order. The service is deliberately lightweight
so that it can be used both from API handlers and from command-line tools
without pulling in heavy dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import requests

from app.ai.config import LLMConfig
from app.ai.exceptions import LLMConnectionError, LLMResponseError


@dataclass(frozen=True, slots=True)
class PurchaseOrderRiskResult:
    """Result returned by :meth:`PurchaseOrderIntelligenceService.assess_risk`.

    Attributes
    ----------
    risk_level:
        One of ``"Low"``, ``"Medium"``, or ``"High"``.
    raw_response:
        The full JSON payload returned by the LLM endpoint.
    """

    risk_level: str
    raw_response: Mapping[str, Any]


class PurchaseOrderIntelligenceService:
    """Service that asks the LLM to evaluate purchase-order risk."""

    _VALID_RISK_LEVELS = {"Low", "Medium", "High"}

    def __init__(self, config: LLMConfig | None = None) -> None:
        """Create a new service instance."""
        self._config = config or LLMConfig.from_env()

    def assess_risk(self, purchase_order: Mapping[str, Any]) -> PurchaseOrderRiskResult:
        """Ask the LLM to assess the risk of *purchase_order*.

        Returns
        -------
        PurchaseOrderRiskResult
            The parsed risk level together with the raw LLM response.

        Raises
        ------
        LLMConnectionError
            If the HTTP request fails.
        LLMResponseError
            If the response is malformed or contains an invalid risk level.
        """
        prompt = self._build_prompt(purchase_order)

        payload = {
            "model": self._config.default_model,
            "prompt": prompt,
            "max_tokens": 50,
            "temperature": 0,
        }

        headers = {
            "Authorization": f"Bearer {self._config.api_key}" if self._config.api_key else "",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                f"{self._config.base_url.rstrip('/')}/v1/completions",
                json=payload,
                headers=headers,
                timeout=self._config.timeout,
            )
            response.raise_for_status()
            raw = response.json()
        except requests.RequestException as exc:
            raise LLMConnectionError(f"Failed to connect to LLM: {exc}") from exc

        try:
            # Extract JSON from the text response
            content = raw["choices"][0]["text"].strip()
            data = json.loads(content)
            risk_level = data["risk_level"]
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
            raise LLMResponseError(f"Malformed LLM response: {raw}") from exc

        if risk_level not in self._VALID_RISK_LEVELS:
            raise LLMResponseError(f"Unexpected risk level: {risk_level!r}")

        return PurchaseOrderRiskResult(risk_level=risk_level, raw_response=raw)

    @staticmethod
    def _build_prompt(purchase_order: Mapping[str, Any]) -> str:
        """Create a prompt requesting JSON output."""
        po_repr = json.dumps(purchase_order, ensure_ascii=False)
        return (
            "You are an expert financial analyst. "
            "Assess the risk of the following purchase order. "
            "Return ONLY a JSON object with the key 'risk_level' "
            "and a value of 'Low', 'Medium', or 'High'.\n"
            f"{po_repr}"
        )
