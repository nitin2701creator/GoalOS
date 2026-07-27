import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app  # Assuming app is exported from app.main

client = TestClient(app)

def test_assess_purchase_order_risk_endpoint():
    payload = {"order_id": "PO-123", "amount": 1000.0, "vendor": "Test Vendor"}
    
    with patch("app.ai.purchase_order.intelligence_service.PurchaseOrderIntelligenceService.assess_risk") as mock_assess:
        mock_assess.return_value = {"risk_level": "Low", "raw_response": {}}
        
        response = client.post("/purchase-orders/intelligence", json=payload)
        
    assert response.status_code == 200
    assert response.json()["risk_level"] == "Low"
