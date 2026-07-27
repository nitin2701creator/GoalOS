from fastapi import APIRouter, HTTPException, Depends
from app.ai.purchase_order.intelligence_service import PurchaseOrderIntelligenceService, PurchaseOrderRiskResult
from app.schemas.purchase_order import PurchaseOrderRequest

router = APIRouter()

@router.post("/purchase-orders/intelligence", response_model=PurchaseOrderRiskResult)
def assess_purchase_order_risk(
    payload: PurchaseOrderRequest,
    service: PurchaseOrderIntelligenceService = Depends(PurchaseOrderIntelligenceService),
):
    try:
        return service.assess_risk(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
