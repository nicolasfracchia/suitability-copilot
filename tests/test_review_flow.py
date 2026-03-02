from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_full_review_flow():
    account_data = {
        "age": 30,
        "income": 50000,
        "net_worth": 20000,
        "risk_tolerance": "Low",
        "investment_choice": "High-growth equities",
        "investment_horizon": 3,
        "notes": "Looking for fast gains"
    }

    res = client.post("/accounts", json=account_data)
    assert res.status_code == 200
    account_id = res.json()["account_id"]

    review_res = client.post(f"/accounts/{account_id}/review")
    assert review_res.status_code == 200
    assert review_res.json()["decision"] in ["APPROVE", "ESCALATE"]