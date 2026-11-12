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
    offer_type: Optional[str] = "AUTO"


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
        "env_diagnostics": {
            "paypal_client_id_len": len(paypal_client.client_id),
            "paypal_client_id_preview": (paypal_client.client_id[:4] + "...") if paypal_client.client_id else "NONE",
            "paypal_client_secret_len": len(paypal_client.client_secret),
            "paypal_base_url": paypal_client.base_url,
            "gemini_api_key_set": bool(os.getenv("GEMINI_API_KEY")),
        }
    }


@app.get("/api/events")
def get_events():
    """Return all recorded audit logs in chronological descending order."""
    return {"events": audit_logs}


@app.delete("/api/events")
def clear_events():
    """Clear all in-memory audit logs."""
    audit_logs.clear()
    return {"status": "cleared", "total_events": 0}


@app.get("/api/logs")
def get_logs():
    """Direct audit log list endpoint for project doc specification compatibility."""
    return audit_logs


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
        discounted_amt = recovery_inv.get("discounted_amount", req.amount)
        payer_view_url = recovery_inv.get("payer_view_url")

        record_log(
            event_type="BILLING_PAYMENT_FAILED",
            status="RECOVERED",
            summary=f"AI Copilot: Evaluated subscriber tenure ({req.tenure_months} months), assigned {discount_pct:.1f}% retention discount (${discounted_amt:.2f} renewal for {req.email})",
            ai_rationale=ai_eval.get("rationale", f"AI Copilot: Evaluated subscriber tenure ({req.tenure_months} months), assigned a {discount_pct:.1f}% retention discount."),
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
            preferred_offer_type=req.offer_type,
            paypal_client=paypal_client,
        )

        ai_eval = result.get("ai_evaluation", {})
        offer_type = ai_eval.get("offer_type", "REFUND")
        settlement_amt = ai_eval.get("settlement_amount", 0.0)
        settlement_pct = ai_eval.get("settlement_percent", 0.0)

        if offer_type == "REPLACEMENT_WITHOUT_REFUND":
            summary = f"AI Copilot: Assessed inquiry risk ({ai_eval.get('risk_score', 50)}/100), dispatched REPLACEMENT_WITHOUT_REFUND on case {req.dispute_id} (100% Cash Retained)"
        else:
            summary = f"AI Copilot: Assessed inquiry risk ({ai_eval.get('risk_score', 65)}/100), offered {settlement_pct:.0f}% settlement refund (${settlement_amt:.2f} on case {req.dispute_id})"

        record_log(
            event_type="CUSTOMER_DISPUTE_INQUIRY",
            status="SETTLEMENT_OFFERED",
            summary=summary,
            ai_rationale=ai_eval.get("rationale", "Pre-chargeback inquiry risk mitigation: settling proactively eliminates fixed merchant dispute penalty fees."),
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
            discount_pct = ai_eval.get("discount_percent", 17.5)
            discounted_amt = recovery_inv.get("discounted_amount", round(amount * (1.0 - discount_pct / 100.0), 2))
            record_log(
                event_type=event_type,
                status="PROCESSED",
                summary=f"AI Copilot: Evaluated subscriber tenure ({tenure} months), assigned {discount_pct:.1f}% retention discount (${discounted_amt:.2f} renewal for {email})",
                ai_rationale=ai_eval.get("rationale", f"AI Copilot: Evaluated subscriber tenure ({tenure} months), assigned a {discount_pct:.1f}% retention discount."),
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
            wh_offer_type = ai_eval.get("offer_type", "REFUND")
            settle_pct = ai_eval.get("settlement_percent", 40.0)
            settle_amt = ai_eval.get("settlement_amount", round(amount * settle_pct / 100.0, 2))

            if wh_offer_type == "REPLACEMENT_WITHOUT_REFUND":
                wh_summary = f"AI Copilot: Assessed inquiry risk ({ai_eval.get('risk_score', 50)}/100), dispatched REPLACEMENT_WITHOUT_REFUND on case {dispute_id} (100% Cash Retained)"
            else:
                wh_summary = f"AI Copilot: Assessed inquiry risk ({ai_eval.get('risk_score', 65)}/100), offered {settle_pct:.0f}% settlement refund (${settle_amt:.2f} on case {dispute_id})"

            record_log(
                event_type=event_type,
                status="SETTLEMENT_OFFERED",
                summary=wh_summary,
                ai_rationale=ai_eval.get("rationale", "Pre-chargeback inquiry risk mitigation: settling proactively eliminates fixed merchant dispute penalty fees."),
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
@app.post("/api/webhook")
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


class TriggerPayload(BaseModel):
    event_type: str
    email: Optional[str] = "customer@example.com"
    amount: Optional[str] = "29.99"
    dispute_id: Optional[str] = "PP-D-12345"


@app.post("/api/trigger")
async def handle_manual_trigger(payload: TriggerPayload, background_tasks: BackgroundTasks):
    """Manual trigger compatibility endpoint as defined in project doc."""
    mock_payload = {
        "event_type": payload.event_type,
        "email": payload.email,
        "dispute_id": payload.dispute_id,
        "resource": {
            "amount": {"total": payload.amount},
            "dispute_amount": {"value": payload.amount},
            "subscriber": {"email_address": payload.email},
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        },
    }
    background_tasks.add_task(process_webhook_event, mock_payload)
    return {"status": "QUEUED", "event_type": payload.event_type}


class CloudSimulateRequest(BaseModel):
    event_type: str = "BILLING.SUBSCRIPTION.PAYMENT.FAILED"


@app.get("/api/webhook/status")
def get_webhook_status():
    """Retrieve active PayPal Sandbox webhook registration and tunnel status."""
    try:
        webhooks = paypal_client.get_registered_webhooks()
        return {
            "status": "connected" if webhooks else "disconnected",
            "active_webhooks": webhooks,
            "total_webhooks": len(webhooks),
            "primary_url": webhooks[0]["url"] if webhooks else None,
            "webhook_id": webhooks[0]["id"] if webhooks else None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "active_webhooks": [],
            "total_webhooks": 0,
        }


@app.post("/api/webhook/simulate-cloud")
def simulate_cloud_event(req: CloudSimulateRequest):
    """
    Trigger an official synthetic test event directly from PayPal Sandbox cloud simulator.
    PayPal will send the webhook across the public internet to PayGuardian.
    """
    try:
        res = paypal_client.simulate_cloud_webhook(event_type=req.event_type)
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to dispatch PayPal cloud simulation: {str(exc)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
