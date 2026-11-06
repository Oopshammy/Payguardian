# 🛡️ PayGuardian

**Autonomous Revenue Recovery & Pre-Chargeback Dispute Arbitration Copilot**  
Built natively on **PayPal Sandbox APIs** and **Google GenAI (Gemini)** for the **Devpost PayPal AI Hackathon**.

---

## 🚀 Overview

PayGuardian protects merchant margins by autonomously resolving two primary friction points:
1. **Subscription Churn Recovery**: Automatically detects failed subscription payments (`BILLING.SUBSCRIPTION.PAYMENT.FAILED`), calculates an optimal tenure-weighted retention discount (10–25%) using Gemini, and dispatches a PayPal invoice directly to the customer.
2. **Pre-Chargeback Dispute Arbitration**: Intervenes at the customer `INQUIRY` stage (`CUSTOMER.DISPUTE.CREATED`), analyzes dispute risk via Gemini, and automatically offers a 30–50% settlement refund to eliminate formal bank chargeback fees ($20–$50) and network penalties.

---

## 📁 Repository Structure

```text
payguardian/
├── backend/
│   ├── app.py              # FastAPI server with simulation & webhook endpoints
│   ├── agent.py            # Gemini (google-genai) autonomous copilot logic
│   ├── paypal_client.py    # PayPal Sandbox OAuth, Invoicing, and Dispute API client
│   ├── requirements.txt    # Python dependencies
│   ├── .env.example        # Environment variables template
│   └── .env                # Local secrets (excluded from git)
├── frontend/
│   └── index.html          # Vanilla JS/CSS real-time monitoring dashboard
├── .gitignore              # Protects secrets and cached files
└── README.md
```

---

## 🛠️ Getting Started

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/<YOUR_USERNAME>/payguardian.git
cd payguardian/backend
```

Create a `.env` file from the example:
```bash
cp .env.example .env
```

Configure your credentials in `backend/.env`:
```env
PAYPAL_CLIENT_ID=your_paypal_sandbox_client_id
PAYPAL_CLIENT_SECRET=your_paypal_sandbox_client_secret
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
GEMINI_API_KEY=your_gemini_api_key
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the Backend & Dashboard
```bash
uvicorn app:app --reload --port 8000
```
Open **`http://127.0.0.1:8000`** in your browser to view the interactive dashboard.

---

## 📡 Webhook Integration

PayGuardian handles incoming PayPal Sandbox webhooks asynchronously:
- `BILLING.SUBSCRIPTION.PAYMENT.FAILED` ➡️ Autonomous churn recovery invoice workflow
- `CUSTOMER.DISPUTE.CREATED` ➡️ Pre-chargeback inquiry risk evaluation & settlement offer

Webhook endpoint:
```http
POST /api/paypal/webhook
```

