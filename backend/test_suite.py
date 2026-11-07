import sys
import os
import json
import time

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_endpoints():
    print("[1/5] Testing Health Check...")
    res = client.get("/api/health")
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200

    print("[2/5] Testing Dashboard Root (index.html)...")
    res = client.get("/")
    print(f"Status: {res.status_code}, Content-Length: {len(res.content)}")
    assert res.status_code == 200

    print("[3/5] Testing Events List...")
    res = client.get("/api/events")
    print(f"Status: {res.status_code}, Event count: {len(res.json().get('events', []))}")
    assert res.status_code == 200

    print("[4/5] Testing Webhook Ingestion (Async background task)...")
    payload_billing = {
        "event_type": "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
        "resource": {
            "subscriber": {"email_address": "john.doe@example.com"},
            "amount": {"total": "39.99"}
        }
    }
    res = client.post("/api/paypal/webhook", json=payload_billing)
    print(f"Webhook billing response: {res.status_code}, {res.json()}")
    assert res.status_code == 200

    payload_dispute = {
        "event_type": "CUSTOMER.DISPUTE.CREATED",
        "resource": {
            "dispute_id": "PP-D-TEST-123",
            "dispute_amount": {"value": "89.00"},
            "reason": "UNRECOGNISED"
        }
    }
    res = client.post("/api/paypal/webhook", json=payload_dispute)
    print(f"Webhook dispute response: {res.status_code}, {res.json()}")
    assert res.status_code == 200

    # Wait briefly for background tasks
    time.sleep(2)

    res_events = client.get("/api/events")
    events = res_events.json().get("events", [])
    print(f"Recorded events after webhook: {len(events)}")
    for e in events:
        print(f" - [{e.get('event_type')}] status={e.get('status')} summary={e.get('summary')[:60]}...")

    print("[5/5] Testing Simulation APIs (Direct PayPal & Gemini calls)...")
    t0 = time.time()
    try:
        res = client.post("/api/simulate/failed-billing", json={
            "email": "sarah.connor@example.com",
            "amount": 29.99,
            "tenure_months": 18
        })
        print(f"Failed-billing simulation returned in {time.time()-t0:.2f}s with status {res.status_code}")
    except Exception as exc:
        print(f"Failed-billing simulation exception: {exc}")

if __name__ == "__main__":
    test_endpoints()
    print("=== FINISHED ===")
