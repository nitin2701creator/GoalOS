from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_ceo_plan_returns_structured_business_plan():
    response = client.post(
        "/api/v1/ceo/plan",
        json={"goal": "Increase Organigram revenue to ₹1 crore/month"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["goal"] == "Increase Organigram revenue to ₹1 crore/month"
    assert data["executive_owner"] == "CEO"
    assert data["priority"] == "critical"
    assert data["timeline"]
    assert data["objectives"]
    assert data["departments"]
    assert data["KPIs"]
    assert data["milestones"]
    assert data["risks"]
    assert data["next_actions"]


def test_ceo_plan_endpoint_is_in_openapi_schema():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/ceo/plan" in response.json()["paths"]
