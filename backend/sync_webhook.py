import os
import sys
import requests

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paypal_client import PayPalClient

client = PayPalClient()
token = client.get_access_token()
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

def sync(target_url: str):
    # 1. Fetch existing webhooks
    res = requests.get(f"{client.base_url}/v1/notifications/webhooks", headers=headers)
    webhooks = res.json().get("webhooks", [])
    print(f"Existing webhooks on PayPal Sandbox ({len(webhooks)}):")
    for wh in webhooks:
        print(f"  - ID: {wh['id']}, URL: {wh['url']}")
        # delete old webhooks
        del_res = requests.delete(f"{client.base_url}/v1/notifications/webhooks/{wh['id']}", headers=headers)
        print(f"    Deleted status: {del_res.status_code}")

    # 2. Register the target webhook
    payload = {
        "url": target_url,
        "event_types": [
            {"name": "BILLING.SUBSCRIPTION.PAYMENT.FAILED"},
            {"name": "CUSTOMER.DISPUTE.CREATED"}
        ]
    }
    create_res = requests.post(f"{client.base_url}/v1/notifications/webhooks", headers=headers, json=payload)
    print("Registration response code:", create_res.status_code)
    data = create_res.json()
    print("Active Webhook ID:", data.get("id"))
    print("Registered URL:", data.get("url"))
    print("Subscribed Events:", [e["name"] for e in data.get("event_types", [])])

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://blue-eagle-11.loca.lt/api/webhook"
    sync(url)
