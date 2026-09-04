"""
Razorpay adapter - maps Razorpay's Payments + Settlements API response
shape into the canonical schema.

Design Decisions:
-----------------
We maintain the 3-source model (Bank, Gateway, ERP):

1. gateway_row: Mapped from the Razorpay Payments API response.
   - settlement_id: "RZP-" + payment id
   - txn_ref: payment `id` (e.g. "pay_xxxxx")
   - gross_amount: payment `amount` / 100 (paise → rupees)
   - fee: payment `fee` / 100
   - tax: payment `tax` / 100
   - refund: payment `amount_refunded` / 100
   - net_amount: gross - fee - tax - refund
   - settled_date: ISO date from payment `created_at`

2. erp_row: Synthetic ERP entries matching the Razorpay payments.
   - entry_id: "ERP-" + payment id
   - txn_ref: payment id
   - amount: gross_amount (what the customer paid)
   - entry_date: same as settled_date
   - account_code: "4000-RAZORPAY-LIVE"

3. bank_row: SIMULATED — Razorpay's API does NOT include your merchant
   bank account's actual statement (that's a separate real-world system).
   In production, bank data arrives via a separate NEFT/bank feed.
   For the demo, we simulate bank rows from settlement net amounts,
   with one deliberate mismatch planted to demonstrate the verifier
   catching discrepancies.

   This is clearly labeled as simulated — not hidden or presented as
   if it came from Razorpay. In the pitch: "These are real Razorpay
   test-mode payment IDs. The bank side is simulated, exactly as it
   would be since bank statements come from a separate system."
"""

import os
import random
from datetime import datetime, timezone


def normalize_source(from_timestamp=None, to_timestamp=None, count=50):
    """
    Fetch real Razorpay test-mode payments and return canonical
    (bank_rows, gateway_rows, erp_rows) tuples.

    Requires RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in environment.
    """
    import razorpay

    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        raise RuntimeError(
            "Razorpay adapter requires RAZORPAY_KEY_ID and "
            "RAZORPAY_KEY_SECRET in your .env file. "
            "Generate test-mode keys from Razorpay Dashboard → "
            "Settings → API Keys."
        )

    client = razorpay.Client(auth=(key_id, key_secret))

    # Fetch payments
    params = {"count": count}
    if from_timestamp:
        params["from"] = from_timestamp
    if to_timestamp:
        params["to"] = to_timestamp

    payments = client.payment.all(params).get("items", [])

    gateway_rows = []
    erp_rows = []

    for p in payments:
        # Only reconcile captured (completed) payments
        if p.get("status") != "captured":
            continue

        txn_ref = p["id"]  # e.g. "pay_xxxxx"
        gross = p["amount"] / 100.0  # paise → rupees
        fee = p.get("fee", 0) or 0
        fee = fee / 100.0
        tax = p.get("tax", 0) or 0
        tax = tax / 100.0
        refund = p.get("amount_refunded", 0) or 0
        refund = refund / 100.0
        net = gross - fee - tax - refund

        settled_date = datetime.fromtimestamp(
            p["created_at"], tz=timezone.utc
        ).date().isoformat()

        gateway_rows.append({
            "settlement_id": f"RZP-{txn_ref}",
            "txn_ref": txn_ref,
            "gross_amount": str(gross),
            "fee": str(fee),
            "tax": str(tax),
            "refund": str(refund),
            "net_amount": str(net),
            "settled_date": settled_date,
        })

        erp_rows.append({
            "entry_id": f"ERP-{txn_ref}",
            "txn_ref": txn_ref,
            "amount": str(gross),
            "entry_date": settled_date,
            "account_code": "4000-RAZORPAY-LIVE",
        })

    if not gateway_rows:
        raise RuntimeError(
            "No captured payments found in Razorpay test account. "
            "Create test orders and simulate payments using Razorpay's "
            "documented test card numbers first."
        )

    # ── Simulated bank statement ─────────────────────────────────────
    # Clearly labeled: bank data is NOT from Razorpay's API.
    rng = random.Random(7)  # deterministic seed for reproducibility
    bank_rows = []

    for i, gw in enumerate(gateway_rows):
        bank_amount = float(gw["net_amount"])

        # Plant one deliberate mismatch for the demo (3rd transaction)
        if i == 2 and len(gateway_rows) > 3:
            bank_amount = round(bank_amount - 500.0, 2)

        bank_rows.append({
            "bank_id": f"BNK-RZP-{i:03d}",
            "date": gw["settled_date"],
            "description": "NEFT CR Razorpay Settlement",
            "ref_number": gw["txn_ref"],
            "credit": str(bank_amount),
            "debit": "0.0",
        })

    print(f"Razorpay adapter: loaded {len(gateway_rows)} captured payments, "
          f"generated {len(bank_rows)} simulated bank rows")

    return bank_rows, gateway_rows, erp_rows
