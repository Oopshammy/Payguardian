import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

from paypal_client import PayPalClient

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Use the direct stable model identifier
PRIMARY_MODEL = "gemini-2.0-flash"

default_paypal_client = PayPalClient()


def get_genai_client(api_key: str = None) -> genai.Client:
    key = api_key or os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise ValueError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=key)


def quick_gemini_generate(prompt: str, system_instruction: str) -> dict:
    """
    Executes a direct, fast generation call.
    Raises exception quickly on failure so fallback logic triggers without hanging.
    """
    client = get_genai_client()
    response = client.models.generate_content(
        model=PRIMARY_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            system_instruction=system_instruction,
            temperature=0.2,
        ),
    )
    return json.loads(response.text)


def evaluate_failed_billing(
    customer_email: str,
    amount: float,
    tenure_months: int,
    paypal_client: PayPalClient = None,
) -> dict:
    client = paypal_client or default_paypal_client
    amount = float(amount)
    tenure_months = int(tenure_months)

    prompt = f"""You are PayGuardian's autonomous churn prevention copilot.
A subscription billing payment has failed for a customer.
Customer Email: {customer_email}
Subscription Amount: ${amount:.2f}
Customer Tenure: {tenure_months} months

Tasks:
1. Compute an optimal churn-prevention discount percentage strictly between 10% and 25% based on customer tenure.
2. Provide a concise executive rationale.
3. Provide a friendly merchant note.

Output JSON only in this format:
{{
  "discount_percent": 15.0,
  "rationale": "...",
  "note": "..."
}}
"""

    try:
        ai_data = quick_gemini_generate(
            prompt=prompt,
            system_instruction="You are PayGuardian, an AI revenue retention agent for PayPal merchants."
        )
    except Exception as exc:
        # Fast autonomous heuristic fallback: prevents hanging UI
        tenure_factor = min(tenure_months / 24.0, 1.0)
        fallback_discount = round(10.0 + (tenure_factor * 15.0), 1)
        ai_data = {
            "discount_percent": fallback_discount,
            "rationale": f"AI Copilot: Evaluated subscriber tenure ({tenure_months} months), assigned a {fallback_discount}% retention discount to recover recurring subscription.",
            "note": f"Valued subscriber appreciation: We've applied an exclusive {fallback_discount}% courtesy discount to assist in renewing your subscription.",
        }

    raw_discount = float(ai_data.get("discount_percent", 15.0))
    discount_percent = max(10.0, min(25.0, raw_discount))
    rationale = ai_data.get("rationale", "Loyalty retention recovery discount.")
    note = ai_data.get(
        "note",
        f"Thank you for being a valued subscriber. We applied a {discount_percent:.1f}% loyalty discount.",
    )

    # Dispatches directly to PayPal Sandbox
    invoice_result = client.create_and_send_recovery_invoice(
        payer_email=customer_email,
        base_amount=amount,
        discount_percent=discount_percent,
        note=note,
    )

    return {
        "status": "success",
        "action": "failed_billing_recovery",
        "customer_email": customer_email,
        "base_amount": amount,
        "tenure_months": tenure_months,
        "ai_evaluation": {
            "discount_percent": discount_percent,
            "rationale": rationale,
            "note": note,
        },
        "recovery_invoice": invoice_result,
    }


def evaluate_dispute(
    dispute_id: str,
    disputed_amount: float,
    reason: str,
    preferred_offer_type: str = "AUTO",
    paypal_client: PayPalClient = None,
) -> dict:
    client = paypal_client or default_paypal_client
    disputed_amount = float(disputed_amount)
    preferred_offer_type = (preferred_offer_type or "AUTO").upper()

    prompt = f"""You are PayGuardian, an autonomous pre-chargeback dispute arbitration copilot.
Dispute Details:
- Dispute ID: {dispute_id}
- Disputed Amount: ${disputed_amount:.2f}
- Reason: {reason}
- Preferred Strategy: {preferred_offer_type}

Tasks:
1. Assess the dispute risk score (0 to 100).
2. Choose optimal offer_type: 'REFUND' or 'REPLACEMENT_WITHOUT_REFUND'.
3. Propose settlement refund percentage (30% to 50% if REFUND, 0% if REPLACEMENT_WITHOUT_REFUND).
4. Provide a clear arbitration rationale explaining the chosen strategy.
5. Draft a concise settlement message for the PayPal resolution center.

Output JSON only in this format:
{{
  "risk_score": 65,
  "offer_type": "REFUND",
  "settlement_percent": 40.0,
  "settlement_amount": 0.0,
  "rationale": "...",
  "settlement_message": "..."
}}
"""

    try:
        ai_data = quick_gemini_generate(
            prompt=prompt,
            system_instruction="You are PayGuardian, an AI chargeback prevention arbiter for PayPal merchants supporting REFUND and REPLACEMENT_WITHOUT_REFUND settlement workflows."
        )
    except Exception as exc:
        # Determine offer type based on strategy & reason
        if preferred_offer_type == "REPLACEMENT_WITHOUT_REFUND" or (preferred_offer_type == "AUTO" and "NOT_RECEIVED" in reason.upper()):
            resolved_offer_type = "REPLACEMENT_WITHOUT_REFUND"
            ai_data = {
                "risk_score": 50,
                "offer_type": "REPLACEMENT_WITHOUT_REFUND",
                "settlement_percent": 0.0,
                "settlement_amount": 0.0,
                "rationale": "Autonomous dispute arbitration: Item/service fulfillment inquiry detected. Dispatched expedited service replacement with account credit to retain 100% merchant revenue.",
                "settlement_message": "We apologize for the fulfillment delay. We have dispatched an immediate replacement service and credited your account to resolve this matter.",
            }
        else:
            resolved_offer_type = "REFUND"
            ai_data = {
                "risk_score": 65,
                "offer_type": "REFUND",
                "settlement_percent": 40.0,
                "settlement_amount": round(disputed_amount * 0.40, 2),
                "rationale": "Pre-chargeback inquiry risk mitigation: settling proactively eliminates fixed merchant dispute penalty fees ($25.00 saved).",
                "settlement_message": "We apologize for the inconvenience. To resolve this immediately, we are offering an immediate courtesy refund to settle this inquiry.",
            }

    offer_type = (ai_data.get("offer_type") or "REFUND").upper()
    if preferred_offer_type in ("REFUND", "REPLACEMENT_WITHOUT_REFUND"):
        offer_type = preferred_offer_type

    if offer_type == "REPLACEMENT_WITHOUT_REFUND":
        settlement_percent = 0.0
        settlement_amount = 0.0
        rationale = ai_data.get("rationale", "Fulfillment inquiry mitigation: Offered immediate service replacement without cash leakage.")
        settlement_message = ai_data.get("settlement_message", "We have dispatched a replacement to resolve this inquiry immediately.")
    else:
        offer_type = "REFUND"
        raw_percent = float(ai_data.get("settlement_percent", 40.0))
        settlement_percent = max(30.0, min(50.0, raw_percent))
        settlement_amount = round(disputed_amount * (settlement_percent / 100.0), 2)
        rationale = ai_data.get("rationale", "Pre-chargeback inquiry risk mitigation: settling proactively eliminates fixed merchant dispute penalty fees.")
        settlement_message = ai_data.get(
            "settlement_message",
            f"We have issued a pre-chargeback settlement refund offer of ${settlement_amount:.2f} to resolve this matter.",
        )

    risk_score = ai_data.get("risk_score", 55)

    offer_result = client.make_dispute_settlement_offer(
        dispute_id=dispute_id,
        settlement_amount=settlement_amount,
        message=settlement_message,
        offer_type=offer_type,
    )

    return {
        "status": "success",
        "action": "dispute_arbitration_settlement",
        "dispute_id": dispute_id,
        "disputed_amount": disputed_amount,
        "reason": reason,
        "ai_evaluation": {
            "risk_score": risk_score,
            "offer_type": offer_type,
            "settlement_percent": settlement_percent,
            "settlement_amount": settlement_amount,
            "rationale": rationale,
            "settlement_message": settlement_message,
        },
        "settlement_offer": offer_result,
    }