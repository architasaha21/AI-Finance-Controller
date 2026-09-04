#!/usr/bin/env python3
"""
Matcher agent: proposes which bank row(s) correspond to each ERP/gateway
transaction. Deterministic-first by design:

  Pass 1 (no LLM): exact ref_number, single candidate, amount within
                    policy tolerance, timing within policy tolerance
                    -> auto-matched, high confidence, cheap, fast.

  Pass 2 (LLM):     everything Pass 1 couldn't resolve - zero candidates,
                    multiple candidates (duplicate ref or split settlement),
                    or amount/timing outside tolerance. This is the small
                    minority of rows, which is the point: don't pay LLM
                    cost/latency on the easy majority.

Every proposal produced here is UNVERIFIED - it still has to survive
verifier.py before it counts as reconciled. The matcher's job is to
propose, not to decide.

If ANTHROPIC_API_KEY is not set, Pass 2 falls back to a heuristic stub
so the pipeline still runs end-to-end. Swap in the real call once you
have a key - see llm_match() below.
"""
import csv
import json
import os
from collections import defaultdict
from datetime import date


def load_data(data_dir, source="csv"):
    if source == "csv":
        from adapters.csv_adapter import normalize_source as load_csv_source
        return load_csv_source(data_dir)
    elif source == "razorpay":
        from adapters.razorpay_adapter import normalize_source as load_razorpay_source
        return load_razorpay_source()
    else:
        raise ValueError(f"Unknown data source: {source}")


def load_policy(policy_path):
    with open(policy_path, encoding="utf-8") as f:
        return json.load(f)


def index_bank_by_ref(bank_rows):
    idx = defaultdict(list)
    for r in bank_rows:
        idx[r["ref_number"]].append(r)
    return idx


def days_between(d1, d2):
    return abs((date.fromisoformat(d1) - date.fromisoformat(d2)).days)


def deterministic_match(gw_row, erp_row, candidates, policy):
    """Try the cheap, obvious case. Returns a proposal dict or None if
    this pair needs LLM reasoning."""
    if len(candidates) != 1:
        return None  # zero or multiple candidates -> ambiguous, needs LLM

    bank_row = candidates[0]
    net = float(gw_row["net_amount"])
    credit = float(bank_row["credit"])
    amt_diff = abs(credit - net)
    day_diff = days_between(bank_row["date"], erp_row["entry_date"])

    if amt_diff <= policy["amount_tolerance_rupees"] and day_diff <= policy["max_timing_diff_days"]:
        return {
            "txn_ref": gw_row["txn_ref"],
            "proposed_bank_ids": [bank_row["bank_id"]],
            "method": "deterministic",
            "confidence": 1.0,
            "reasoning": f"Exact ref match, amount diff Rs.{amt_diff:.2f} within "
                         f"tolerance, settled {day_diff}d after entry (policy allows "
                         f"{policy['max_timing_diff_days']}d).",
        }
    return None  # amount or timing outside tolerance -> needs LLM judgment


def stub_llm_match(gw_row, erp_row, candidates, policy):
    """Heuristic stand-in used when no ANTHROPIC_API_KEY is configured.
    Lets you run the full pipeline before wiring up the real model."""
    net = float(gw_row["net_amount"])

    if len(candidates) == 0:
        return {
            "txn_ref": gw_row["txn_ref"],
            "proposed_bank_ids": [],
            "method": "llm-stub",
            "confidence": 0.0,
            "reasoning": "No bank row found for this ref_number at all.",
        }

    if len(candidates) >= 2:
        # could be a duplicate ref (reject-worthy) or a genuine split
        total = sum(float(c["credit"]) for c in candidates)
        if abs(total - net) <= policy["fee_tax_refund_tolerance_rupees"]:
            return {
                "txn_ref": gw_row["txn_ref"],
                "proposed_bank_ids": [c["bank_id"] for c in candidates],
                "method": "llm-stub",
                "confidence": 0.7,
                "reasoning": f"{len(candidates)} bank rows share this ref and sum to "
                             f"within tolerance of net_amount - proposing as a split settlement.",
            }
        # doesn't sum cleanly -> likely duplicate ref, propose the closer one only
        best = min(candidates, key=lambda c: abs(float(c["credit"]) - net))
        return {
            "txn_ref": gw_row["txn_ref"],
            "proposed_bank_ids": [best["bank_id"]],
            "method": "llm-stub",
            "confidence": 0.5,
            "reasoning": f"{len(candidates)} bank rows share this ref but do not sum to "
                         f"net_amount - likely a duplicate/reused reference. Proposing the "
                         f"closer amount match, flagging low confidence for verifier.",
        }

    # exactly 1 candidate but Pass 1 rejected it (amount or timing off)
    bank_row = candidates[0]
    amt_diff = abs(float(bank_row["credit"]) - net)
    if amt_diff <= policy["fee_tax_refund_tolerance_rupees"]:
        conf = 0.8
        reason = f"Amount diff Rs.{amt_diff:.2f} explainable by fee/tax/refund rounding."
    elif amt_diff <= policy["unexplained_variance_review_threshold_rupees"]:
        conf = 0.5
        reason = f"Amount diff Rs.{amt_diff:.2f} exceeds simple rounding, not clearly explained."
    else:
        conf = 0.2
        reason = f"Amount diff Rs.{amt_diff:.2f} large and unexplained."
    return {
        "txn_ref": gw_row["txn_ref"],
        "proposed_bank_ids": [bank_row["bank_id"]],
        "method": "llm-stub",
        "confidence": conf,
        "reasoning": reason,
    }


def llm_match(gw_row, erp_row, candidates, policy):
    """Real LLM call. Fill this in once ANTHROPIC_API_KEY is set.
    Kept separate from stub_llm_match so swapping is a one-line change
    in run_matcher() below."""
    import anthropic  # pip install anthropic
    client = anthropic.Anthropic()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    prompt = f"""You are the matcher component of a finance reconciliation agent.
Propose which bank row(s), if any, correspond to this ERP/gateway transaction.
You are NOT the final decision-maker - a separate verifier agent will audit
your proposal, so it is fine to propose a low-confidence match and flag your
uncertainty rather than refusing to answer.

ERP entry: {json.dumps(erp_row)}
Gateway settlement: {json.dumps(gw_row)}
Candidate bank rows: {json.dumps(candidates)}
Policy tolerances: {json.dumps(policy)}

Respond with ONLY a JSON object, no other text:
{{
  "proposed_bank_ids": [...],
  "confidence": 0.0-1.0,
  "reasoning": "one or two sentences, plain language, reference specific numbers"
}}"""

    resp = client.messages.create(
        model=model,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(text)
    return {
        "txn_ref": gw_row["txn_ref"],
        "proposed_bank_ids": parsed["proposed_bank_ids"],
        "method": "llm",
        "confidence": parsed["confidence"],
        "reasoning": parsed["reasoning"],
    }


def run_matcher(data_dir, policy_path, use_real_llm=False, source="csv"):
    bank, gateway, erp = load_data(data_dir, source=source)
    policy = load_policy(policy_path)
    bank_by_ref = index_bank_by_ref(bank)
    erp_by_ref = {r["txn_ref"]: r for r in erp}

    proposals = []
    deterministic_count = 0
    llm_count = 0

    for gw_row in gateway:
        ref = gw_row["txn_ref"]
        erp_row = erp_by_ref[ref]
        candidates = bank_by_ref.get(ref, [])

        proposal = deterministic_match(gw_row, erp_row, candidates, policy)
        if proposal is not None:
            deterministic_count += 1
        else:
            llm_count += 1
            if use_real_llm:
                proposal = llm_match(gw_row, erp_row, candidates, policy)
            else:
                proposal = stub_llm_match(gw_row, erp_row, candidates, policy)

        proposal["gw_row"] = gw_row
        proposal["erp_row"] = erp_row
        proposal["candidates"] = candidates
        proposals.append(proposal)

    print(f"Matcher: {deterministic_count} resolved deterministically "
          f"({deterministic_count/len(gateway)*100:.0f}%), "
          f"{llm_count} sent to LLM matcher ({llm_count/len(gateway)*100:.0f}%)")

    return proposals, policy


if __name__ == "__main__":
    import sys
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "../data/output"
    policy_path = sys.argv[2] if len(sys.argv) > 2 else "policy.json"
    use_real_llm = os.environ.get("ANTHROPIC_API_KEY") is not None
    if use_real_llm:
        print("ANTHROPIC_API_KEY found - using real LLM matcher for ambiguous cases")
    else:
        print("No ANTHROPIC_API_KEY set - using heuristic stub matcher (fine for dev/testing)")
    proposals, policy = run_matcher(data_dir, policy_path, use_real_llm=use_real_llm)
    for p in proposals[:5]:
        print(f"  {p['txn_ref']}: {p['method']} conf={p['confidence']:.2f} -> {p['proposed_bank_ids']}")
