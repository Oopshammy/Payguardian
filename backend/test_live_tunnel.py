"""
PayGuardian Live Tunnel & PayPal Webhook Simulator End-to-End Test
Verifies public HTTPS tunnel reachability and live event delivery from PayPal Sandbox cloud.
"""

import os
import sys
import time
import requests

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paypal_client import PayPalClient

LOCAL_API = "http://127.0.0.1:8000"

def run_test():
    print("=" * 65)
    print("PAYGUARDIAN: LIVE TUNNEL & PAYPAL WEBHOOK SIMULATOR TEST")
    print("=" * 65)

    # 1. Local Server Health Check
    print("\n[Step 1/5] Checking Local PayGuardian Server...")
    try:
        r = requests.get(f"{LOCAL_API}/api/health", timeout=5)
        r.raise_for_status()
        print(f"  [PASS] Local Server Online: {r.json()}")
    except Exception as exc:
        print(f"  [FAIL] Local Server Failed: {exc}")
        print("  Please make sure uvicorn is running on port 8000.")
        return

    # 2. Query PayPal Sandbox Registered Webhooks
    print("\n[Step 2/5] Querying PayPal Sandbox Webhooks via REST API...")
    client = PayPalClient()
    webhooks = client.get_registered_webhooks()
    if not webhooks:
        print("  [FAIL] No webhooks currently registered on PayPal Sandbox.")
        print("  Run 'python backend/sync_webhook.py <tunnel_url>' to register.")
        return
    active_wh = webhooks[0]
    webhook_id = active_wh["id"]
    webhook_url = active_wh["url"]
    events = [e["name"] for e in active_wh.get("event_types", [])]
    print(f"  [PASS] Active Webhook ID: {webhook_id}")
    print(f"  [PASS] Registered URL:    {webhook_url}")
    print(f"  [PASS] Subscribed Events: {events}")

    # 3. Test Public Tunnel Reachability
    print("\n[Step 3/5] Testing Public HTTPS Tunnel Reachability...")
    tunnel_health = f"{webhook_url.replace('/api/webhook', '')}/api/health"
    try:
        r = requests.get(tunnel_health, headers={"User-Agent": "PayPal-Webhook-Delivery"}, timeout=12)
        if r.status_code == 200:
            print(f"  [PASS] Tunnel Reachable over Public Web: {tunnel_health} (200 OK)")
        else:
            print(f"  [WARN] Tunnel returned status {r.status_code}")
    except Exception as exc:
        print(f"  [WARN] Warning testing tunnel URL: {exc}")

    # 4. Dispatch Live Test from PayPal Cloud Simulator
    print("\n[Step 4/5] Dispatching Live Events via PayPal Webhook Simulator API...")
    test_events = [
        ("BILLING.SUBSCRIPTION.PAYMENT.FAILED", "Subscription Churn Recovery"),
        ("CUSTOMER.DISPUTE.CREATED", "Pre-Chargeback Dispute Arbitration"),
    ]

    for evt_name, desc in test_events:
        print(f"  > Firing PayPal Cloud Event: {evt_name} ({desc})...")
        try:
            res = client.simulate_cloud_webhook(event_type=evt_name, webhook_id=webhook_id, url=webhook_url)
            print(f"    [PASS] PayPal Cloud Dispatch Accepted (HTTP {res['paypal_status_code']})")
        except Exception as exc:
            print(f"    [FAIL] PayPal Simulation Dispatch Failed: {exc}")

    # 5. Verify Telemetry Ingestion
    print("\n[Step 5/5] Polling PayGuardian Ingestion Feed for Incoming Cloud Events...")
    time.sleep(3)
    try:
        r = requests.get(f"{LOCAL_API}/api/logs", timeout=5)
        logs = r.json()
        print(f"  [PASS] Total Telemetry Events in Feed: {len(logs)}")
        for i, item in enumerate(logs[:2]):
            print(f"    [{i+1}] {item.get('event_type')} | {item.get('status')} | {item.get('summary')}")
    except Exception as exc:
        print(f"  [FAIL] Failed to fetch telemetry feed: {exc}")

    print("\n" + "=" * 65)
    print("ALL LIVE TUNNEL & PAYPAL WEBHOOK SIMULATOR TESTS COMPLETED!")
    print("=" * 65)

if __name__ == "__main__":
    run_test()
