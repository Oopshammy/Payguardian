import os
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from paypal_client import PayPalClient
from agent import (
    evaluate_failed_billing,
    evaluate_dispute,
)

app = FastAPI(
    title="PayGuardian API",
    description="Autonomous Revenue Recovery & Pre-Chargeback Dispute Arbitration Copilot",
    version="1.0.0",
)

# Permissive CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory audit log store
audit_logs: List[Dict[str, Any]] = []

paypal_client = PayPalClient()


class FailedBillingSimulateRequest(BaseModel):
    email: str
    amount: float
    tenure_months: int


class DisputeSimulateRequest(BaseModel):
    dispute_id: str
    amount: float
    reason: str


def record_log(
    event_type: str,
    status: str,
    summary: str,
    ai_rationale: str = "",
    payer_view_url: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Helper to record structured audit log entries (newest first)."""
    entry = {
        "id": f"evt_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "status": status,
        "summary": summary,
        "ai_rationale": ai_rationale,
        "payer_view_url": payer_view_url,
        "details": details or {},
    }
    audit_logs.insert(0, entry)
    # Keep up to 200 items in memory
    if len(audit_logs) > 200:
        audit_logs.pop()
    return entry


@app.get("/")
def root():
    index_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html"))
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "project": "PayGuardian",
        "status": "online",
        "description": "Autonomous Revenue Recovery & Pre-Chargeback Dispute Arbitration Copilot",
        "total_events": len(audit_logs),
    }


@app.get("/api/health")
def health():
    return {
        "project": "PayGuardian",
        "status": "online",
        "total_events": len(audit_logs),
    }


@app.get("/api/events")
def get_events():
    """Return all recorded audit logs in chronological descending order."""
    return {"events": audit_logs}


@app.post("/api/simulate/failed-billing")
def simulate_failed_billing(req: FailedBillingSimulateRequest):
    """
    Simulation trigger for Scenario A: Failed Subscription.
    Evaluates customer tenure via Gemini, issues a recovery invoice with loyalty discount via PayPal,
    and logs the decision & invoice link.
    """
    try:
        result = evaluate_failed_billing(
            customer_email=req.email,
            amount=req.amount,
            tenure_months=req.tenure_months,
            paypal_client=paypal_client,
        )

        ai_eval = result.get("ai_evaluation", {})
        recovery_inv = result.get("recovery_invoice", {})
        discount_pct = ai_eval.get("discount_percent", 0.0)
        payer_view_url = recovery_inv.get("payer_view_url")

        record_log(
            event_type="BILLING_PAYMENT_FAILED",
            status="RECOVERED",
            summary=f"Dispatched {discount_pct:.1f}% discount invoice to {req.email} (${req.amount:.2f} base)",
            ai_rationale=ai_eval.get("rationale", "Loyalty recovery strategy."),
            payer_view_url=payer_view_url,
            details=result,
        )
        return result
    except Exception as exc:
        record_log(
            event_type="BILLING_PAYMENT_FAILED",
            status="FAILED",
            summary=f"Failed billing recovery error for {req.email}: {str(exc)}",
            ai_rationale=f"Error executing recovery workflow: {str(exc)}",
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/simulate/dispute")
def simulate_dispute(req: DisputeSimulateRequest):
    """
    Simulation trigger for Scenario B: PayPal Dispute Inquiry.
    Evaluates dispute risk at inquiry stage via Gemini, computes settlement offer (30-50%),
    submits offer to PayPal, and logs the decision.
    """
    try:
        result = evaluate_dispute(
            dispute_id=req.dispute_id,
            disputed_amount=req.amount,
            reason=req.reason,
            paypal_client=paypal_client,
        )

        ai_eval = result.get("ai_evaluation", {})
        settlement_amt = ai_eval.get("settlement_amount", 0.0)
        settlement_pct = ai_eval.get("settlement_percent", 0.0)

        record_log(
            event_type="CUSTOMER_DISPUTE_INQUIRY",
            status="SETTLEMENT_OFFERED",
            summary=f"Offered ${settlement_amt:.2f} ({settlement_pct:.0f}%) refund settlement on {req.dispute_id}",
            ai_rationale=ai_eval.get("rationale", "Pre-chargeback dispute mitigation."),
            payer_view_url=None,
            details=result,
        )
        return result
    except Exception as exc:
        record_log(
            event_type="CUSTOMER_DISPUTE_INQUIRY",
            status="FAILED",
            summary=f"Dispute arbitration offer error for {req.dispute_id}: {str(exc)}",
            ai_rationale=f"Error executing dispute workflow: {str(exc)}",
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc))


def process_webhook_event(payload: Dict[str, Any]):
    """Asynchronous background worker for PayPal Sandbox webhook events."""
    event_type = payload.get("event_type", "")
    resource = payload.get("resource", {})

    if event_type == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
        email = (
            resource.get("subscriber", {}).get("email_address")
            or resource.get("payer_email")
            or "subscriber@example.com"
        )
        raw_amt = (
            resource.get("amount", {}).get("total")
            or resource.get("amount", {}).get("value")
            or 49.00
        )
        try:
            amount = float(raw_amt)
        except (ValueError, TypeError):
            amount = 49.00

        tenure = 12  # Standard subscriber baseline
        try:
            res = evaluate_failed_billing(
                customer_email=email,
                amount=amount,
                tenure_months=tenure,
                paypal_client=paypal_client,
            )
            ai_eval = res.get("ai_evaluation", {})
            recovery_inv = res.get("recovery_invoice", {})
            record_log(
                event_type=event_type,
                status="PROCESSED",
                summary=f"Automated recovery invoice generated for {email} (${amount:.2f})",
                ai_rationale=ai_eval.get("rationale", "Webhook autonomous recovery."),
                payer_view_url=recovery_inv.get("payer_view_url"),
                details=res,
            )
        except Exception as exc:
            record_log(
                event_type=event_type,
                status="FAILED",
                summary=f"Webhook processing error for {email}: {str(exc)}",
                details={"error": str(exc), "payload": payload},
            )

    elif event_type == "CUSTOMER.DISPUTE.CREATED":
        dispute_id = resource.get("dispute_id") or payload.get("id") or "PP-D-UNKNOWN"
        raw_amt = (
            resource.get("dispute_amount", {}).get("value")
            or resource.get("amount", {}).get("value")
            or 75.00
        )
        reason = resource.get("reason", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED")
        try:
            amount = float(raw_amt)
        except (ValueError, TypeError):
            amount = 75.00

        try:
            res = evaluate_dispute(
                dispute_id=dispute_id,
                disputed_amount=amount,
                reason=reason,
                paypal_client=paypal_client,
            )
            ai_eval = res.get("ai_evaluation", {})
            record_log(
                event_type=event_type,
                status="PROCESSED",
                summary=f"Automated dispute arbitration settlement offer submitted for {dispute_id}",
                ai_rationale=ai_eval.get("rationale", "Webhook autonomous dispute mitigation."),
                payer_view_url=None,
                details=res,
            )
        except Exception as exc:
            record_log(
                event_type=event_type,
                status="FAILED",
                summary=f"Webhook dispute processing error for {dispute_id}: {str(exc)}",
                details={"error": str(exc), "payload": payload},
            )
    else:
        record_log(
            event_type=event_type or "UNKNOWN_EVENT",
            status="IGNORED",
            summary=f"Received unhandled PayPal webhook event: {event_type}",
            details=payload,
        )


@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Handle PayPal Sandbox webhooks asynchronously.
    Listens for BILLING.SUBSCRIPTION.PAYMENT.FAILED and CUSTOMER.DISPUTE.CREATED.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    background_tasks.add_task(process_webhook_event, payload)
    return {
        "status": "accepted",
        "event_type": payload.get("event_type", "UNKNOWN"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
