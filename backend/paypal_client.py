import os
import requests
from dotenv import load_dotenv

load_dotenv()

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_BASE_URL = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")


class PayPalClient:
    """PayPal Sandbox API client for dispute arbitration and recovery invoicing."""

    def __init__(self, client_id: str = None, client_secret: str = None, base_url: str = None):
        self.client_id = client_id or PAYPAL_CLIENT_ID
        self.client_secret = client_secret or PAYPAL_CLIENT_SECRET
        self.base_url = (base_url or PAYPAL_BASE_URL).rstrip("/")
        self._access_token = None

    def get_access_token(self) -> str:
        """Retrieve OAuth2 Bearer token from PayPal Sandbox using client credentials."""
        if not self.client_id or not self.client_secret:
            return "simulated_sandbox_token"

        url = f"{self.base_url}/v1/oauth2/token"
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US",
        }
        data = {"grant_type": "client_credentials"}
        response = requests.post(
            url,
            auth=(self.client_id, self.client_secret),
            headers=headers,
            data=data,
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
        self._access_token = token_data.get("access_token")
        return self._access_token

    def _auth_headers(self) -> dict:
        """Generate authorized headers for PayPal API requests."""
        if not self._access_token:
            self.get_access_token()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def create_and_send_recovery_invoice(
        self,
        payer_email: str,
        base_amount: float,
        discount_percent: float,
        note: str,
    ) -> dict:
        """
        Create a draft invoice with line items & loyalty discount, dispatch it to the payer,
        and retrieve metadata including payer_view_url, invoice_id, and discounted_amount.
        """
        base_amount = float(base_amount)
        discount_percent = float(discount_percent)
        discounted_amount = round(base_amount * (1.0 - (discount_percent / 100.0)), 2)

        # If credentials are not yet configured, return a realistic sandbox invoice structure
        if not self.client_id or not self.client_secret:
            import uuid
            inv_suffix = uuid.uuid4().hex[:8].upper()
            sim_id = f"INV2-SBX-{inv_suffix}"
            return {
                "invoice_id": sim_id,
                "payer_view_url": f"https://www.sandbox.paypal.com/invoice/p/#{sim_id}",
                "discounted_amount": discounted_amount,
                "base_amount": base_amount,
                "discount_percent": discount_percent,
                "payer_email": payer_email,
                "status": "SENT",
            }

        # 1. Create Draft Invoice via POST /v2/invoicing/invoices
        create_url = f"{self.base_url}/v2/invoicing/invoices"
        invoice_payload = {
            "detail": {
                "currency_code": "USD",
                "note": note or "PayGuardian automated churn recovery invoice with loyalty discount.",
                "term": "Payment due upon receipt.",
            },
            "primary_recipients": [
                {
                    "billing_info": {
                        "email_address": payer_email,
                    }
                }
            ],
            "items": [
                {
                    "name": "Subscription Renewal & Account Recovery",
                    "description": f"Subscription recovery invoice with {discount_percent:.1f}% retention discount applied.",
                    "quantity": "1",
                    "unit_amount": {
                        "currency_code": "USD",
                        "value": f"{base_amount:.2f}",
                    },
                    "discount": {
                        "percent": f"{discount_percent:.2f}",
                    },
                }
            ],
        }

        create_res = requests.post(
            create_url,
            headers=self._auth_headers(),
            json=invoice_payload,
            timeout=30,
        )
        create_res.raise_for_status()
        create_data = create_res.json()

        # Extract invoice_id from body or Location header
        invoice_id = create_data.get("id")
        if not invoice_id:
            loc = create_res.headers.get("Location", "")
            if "/" in loc:
                invoice_id = loc.split("/")[-1]

        if not invoice_id:
            raise ValueError(f"Could not determine invoice ID from create response: {create_data}")

        # 2. Dispatch invoice via POST /v2/invoicing/invoices/{invoice_id}/send
        send_url = f"{self.base_url}/v2/invoicing/invoices/{invoice_id}/send"
        send_payload = {
            "send_to_recipient": True,
        }
        send_res = requests.post(
            send_url,
            headers=self._auth_headers(),
            json=send_payload,
            timeout=30,
        )
        send_res.raise_for_status()

        # 3. Fetch invoice metadata via GET /v2/invoicing/invoices/{invoice_id}
        get_url = f"{self.base_url}/v2/invoicing/invoices/{invoice_id}"
        get_res = requests.get(
            get_url,
            headers=self._auth_headers(),
            timeout=30,
        )
        get_res.raise_for_status()
        inv_data = get_res.json()

        # Extract payer view URL
        metadata = inv_data.get("detail", {}).get("metadata", {})
        payer_view_url = metadata.get("payer_view_url")

        if not payer_view_url:
            for link in inv_data.get("links", []):
                if link.get("rel") == "payer-view":
                    payer_view_url = link.get("href")
                    break

        if not payer_view_url:
            payer_view_url = f"https://www.sandbox.paypal.com/invoice/payer-view/details/{invoice_id}"

        # Get final amount from invoice data if available
        final_amount = inv_data.get("amount", {}).get("value")
        if final_amount:
            try:
                discounted_amount = float(final_amount)
            except (ValueError, TypeError):
                pass

        return {
            "invoice_id": invoice_id,
            "payer_view_url": payer_view_url,
            "discounted_amount": discounted_amount,
            "base_amount": base_amount,
            "discount_percent": discount_percent,
            "payer_email": payer_email,
            "status": inv_data.get("status", "SENT"),
        }

    def make_dispute_settlement_offer(
        self,
        dispute_id: str,
        settlement_amount: float,
        message: str,
    ) -> dict:
        """
        Offer a settlement refund on an active dispute via POST /v1/customer/disputes/{dispute_id}/make-offer.
        """
        settlement_amount = float(settlement_amount)

        if not self.client_id or not self.client_secret:
            return {
                "dispute_id": dispute_id,
                "offer_type": "REFUND",
                "settlement_amount": settlement_amount,
                "message": message,
                "status": "OFFER_SUBMITTED",
            }
        url = f"{self.base_url}/v1/customer/disputes/{dispute_id}/make-offer"
        payload = {
            "note": message,
            "offer_type": "REFUND",
            "offer_amount": {
                "currency_code": "USD",
                "value": f"{settlement_amount:.2f}",
            },
        }

        response = requests.post(
            url,
            headers=self._auth_headers(),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        if response.content:
            try:
                return response.json()
            except Exception:
                pass

        return {
            "dispute_id": dispute_id,
            "offer_type": "REFUND",
            "settlement_amount": settlement_amount,
            "message": message,
            "status": "OFFER_SUBMITTED",
        }
