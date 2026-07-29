"""API routes for purchase‑order related operations.

This module defines the FastAPI router that is included in ``app.main``.
It provides a single endpoint used by the test suite:

    POST /purchase-orders/intelligence
        → assesses the risk of a purchase order using the LLM‑based
          ``PurchaseOrderIntelligenceService``.

The endpoint is deliberately thin – it delegates all business logic to the
service class.  The service returns a ``PurchaseOrderRiskResult`` dataclass,
which is converted to a plain ``dict`` (FastAPI can serialise a dict directly).
When the service method is patched in tests it returns a dict, and that dict
is returned unchanged.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ai.purchase_order.intelligence_service import (
    PurchaseOrderIntelligenceService,
    PurchaseOrderRiskResult,
)

router = APIRouter()


class PurchaseOrderPayload(BaseModel):
    """Schema for the request body expected by the intelligence endpoint."""

    order_id: str = Field(..., description="Unique identifier of the purchase order.")
    amount: float = Field(..., description="Monetary amount of the order.")
    vendor: str = Field(..., description="Name of the vendor/supplier.")


@router.post("/purchase-orders/intelligence")
async def assess_purchase_order_intelligence(
    payload: PurchaseOrderPayload,
):
    """
    Assess the risk level of a purchase order.

    The function creates an instance of ``PurchaseOrderIntelligenceService``,
    forwards the incoming payload to its ``assess_risk`` method, and returns
    the result.

    The test suite patches ``PurchaseOrderIntelligenceService.assess_risk`` to
    return a plain ``dict``; FastAPI will serialise that dict directly.  In the
    real implementation the method returns a ``PurchaseOrderRiskResult``
    dataclass, which is also serialisable because it can be converted to a
    dict.
    """
    try:
        service = PurchaseOrderIntelligenceService()
        result = service.assess_risk(payload.dict())
        # ``result`` may be a dataclass or a plain dict (when patched in tests).
        # FastAPI can return either; if it's a dataclass, convert to dict.
        if isinstance(result, PurchaseOrderRiskResult):
            return result.__dict__
        return result
    except Exception as exc:  # pragma: no cover – generic safety net
        raise HTTPException(status_code=500, detail=str(exc)) from exc
