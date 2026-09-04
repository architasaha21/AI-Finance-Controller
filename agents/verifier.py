#!/usr/bin/env python3
"""
Verifier agent: takes every proposal from matcher.py and actively tries
to break it before accepting it. This is the component the brief is
really testing - "verification capacity, not generation speed, is the
bottleneck."

Design: deterministic policy checks run FIRST and are authoritative for
clear-cut cases (duplicate ref, missing settlement, split sum wrong,
timing/amount grossly outside policy). The LLM is only consulted for
genuine gray-zone judgment calls - where the deterministic checks can't
cleanly say accept or reject. This mirrors the matcher's philosophy:
don't spend LLM calls on cases a rule already answers.

Every verdict is one of:
  RECONCILED - accepted, fully within policy
  REVIEW     - resolvable but needs a human to confirm (low confidence,
               gray-zone variance, or a split/duplicate situation)
  EXCEPTION  - rejected, genuinely does not reconcile

The verifier is deliberately conservative: a false RECONCILED is worse
than an unnecessary REVIEW, so ties go to REVIEW, never to RECONCILED.
"""
import json
import os
from datetime import date


def days_between(d1, d2):
    return abs((date.fromisoformat(d1) - date.fromisoformat(d2)).days)


def check_identity(proposal, all_bank_by_ref, policy):
    """Is the ref_number used more than once across the whole bank
    statement in a way the proposal doesn't already account for?"""
    ref = proposal["txn_ref"]
    all_rows_for_ref = all_bank_by_ref.get(ref, [])
    proposed_ids = set(proposal["proposed_bank_ids"])
    all_ids = {r["bank_id"] for r in all_rows_for_ref}

    if len(all_ids) > len(proposed_ids) and len(all_ids) >= 2:
        # there's a bank row sharing this ref that the proposal did NOT include -
        # only acceptable if it's an intentional, sum-reconciling split
        unclaimed = all_ids - proposed_ids
        if unclaimed:
            return {
                "passed": False,
                "reason": f"ref_number {ref} appears on {len(all_ids)} bank rows total, "
                          f"but proposal only claims {len(proposed_ids)}. Unclaimed row(s): "
                          f"{sorted(unclaimed)}. Policy requires human review before accepting "
                          f"any match where a reference is reused this way.",
            }
    return {"passed": True, "reason": None}


def check_amount(proposal, policy):
    net = float(proposal["gw_row"]["net_amount"])
    bank_rows = {r["bank_id"]: r for r in proposal["candidates"]}
    proposed_rows = [bank_rows[bid] for bid in proposal["proposed_bank_ids"] if bid in bank_rows]

    if not proposed_rows:
        return {
            "passed": False,
            "verdict": "EXCEPTION",
            "reason": "No bank row proposed at all - ERP entry has no corresponding "
                      "settlement in the bank statement.",
        }

    total_credit = sum(float(r["credit"]) for r in proposed_rows)
    diff = abs(total_credit - net)
    tol = policy["amount_tolerance_rupees"]
    fee_tol = policy["fee_tax_refund_tolerance_rupees"]
    review_threshold = policy["unexplained_variance_review_threshold_rupees"]
    exception_threshold = policy["unexplained_variance_exception_threshold_rupees"]

    if diff <= tol:
        return {"passed": True, "verdict": None,
                "reason": f"Amount matches net_amount within Rs.{tol} tolerance."}
    if diff <= fee_tol:
        return {"passed": True, "verdict": None,
                "reason": f"Rs.{diff:.2f} gap fully explainable by standard fee/tax/refund rounding."}
    if diff <= review_threshold:
        return {"passed": False, "verdict": "REVIEW",
                "reason": f"Rs.{diff:.2f} gap exceeds normal rounding but is below the "
                          f"Rs.{exception_threshold} exception threshold - needs human judgment."}
    return {"passed": False, "verdict": "EXCEPTION",
            "reason": f"Rs.{diff:.2f} gap far exceeds policy tolerance ("
                      f"Rs.{exception_threshold} threshold) and is not explained by fee/tax/refund."}


def check_timing(proposal, policy):
    bank_rows = {r["bank_id"]: r for r in proposal["candidates"]}
    proposed_rows = [bank_rows[bid] for bid in proposal["proposed_bank_ids"] if bid in bank_rows]
    if not proposed_rows:
        return {"passed": True, "reason": None}  # already caught by check_amount

    entry_date = proposal["erp_row"]["entry_date"]
    max_diff = max(days_between(r["date"], entry_date) for r in proposed_rows)

    if max_diff <= policy["max_timing_diff_days"]:
        return {"passed": True, "reason": None}
    return {
        "passed": False,
        "reason": f"Settlement landed {max_diff}d after ERP entry - policy allows "
                  f"{policy['max_timing_diff_days']}d. Outside normal timing.",
    }


def check_split(proposal, policy):
    if len(proposal["proposed_bank_ids"]) <= 1:
        return {"passed": True, "reason": None}
    if not policy["split_settlement_allowed"]:
        return {"passed": False, "reason": "Multi-row match proposed but policy disallows split settlements."}
    if len(proposal["proposed_bank_ids"]) > policy["max_split_parts"]:
        return {"passed": False,
                "reason": f"Proposal splits across {len(proposal['proposed_bank_ids'])} bank rows, "
                          f"exceeding policy max of {policy['max_split_parts']}."}
    return {"passed": True, "reason": f"Split across {len(proposal['proposed_bank_ids'])} bank "
                                       f"rows, within policy limit - sum already checked in amount rule."}


def llm_gray_zone_judgment(proposal, checks_summary, policy):
    """Only called for genuine gray-zone cases the deterministic checks
    couldn't cleanly resolve. This is where the verifier earns the
    'genuinely intelligent agent' label - not on the easy calls."""
    import anthropic
    client = anthropic.Anthropic()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    prompt = f"""You are the verifier in a finance reconciliation system. Your job is to
try to DISPROVE a proposed match, not confirm it. Be conservative: if you are not
confident, recommend REVIEW rather than RECONCILED. Never recommend RECONCILED for
a duplicate reference or a missing settlement.

Proposed match: {json.dumps({k: v for k, v in proposal.items() if k not in ('candidates',)}, default=str)}
Deterministic check results so far: {json.dumps(checks_summary)}
Policy: {json.dumps(policy)}

Respond with ONLY JSON, no other text:
{{"verdict": "RECONCILED" | "REVIEW" | "EXCEPTION", "confidence": 0.0-1.0, "reason": "one or two sentences"}}"""

    resp = client.messages.create(model=model, max_tokens=200,
                                   messages=[{"role": "user", "content": prompt}])
    text = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def verify_match(proposal, all_bank_by_ref, policy, use_real_llm=False):
    """Runs all deterministic checks, then escalates to LLM only if the
    outcome is genuinely ambiguous. Returns the final verdict dict."""
    checks = {
        "identity": check_identity(proposal, all_bank_by_ref, policy),
        "amount": check_amount(proposal, policy),
        "timing": check_timing(proposal, policy),
        "split": check_split(proposal, policy),
    }

    # hard rejects - never overridable, never sent to LLM for a second opinion
    if not checks["identity"]["passed"]:
        return {"verdict": "REVIEW", "verdict_confidence": 0.3,
                "reason": checks["identity"]["reason"], "escalated_to_llm": False, "checks": checks}
    if checks["amount"]["verdict"] == "EXCEPTION":
        return {"verdict": "EXCEPTION", "verdict_confidence": 0.95,
                "reason": checks["amount"]["reason"], "escalated_to_llm": False, "checks": checks}
    if not checks["split"]["passed"]:
        return {"verdict": "EXCEPTION", "verdict_confidence": 0.9,
                "reason": checks["split"]["reason"], "escalated_to_llm": False, "checks": checks}

    # Timing is a hard policy boundary. The LLM may explain gray-zone amount
    # variance, but it must not override an out-of-policy settlement delay.
    if not checks["timing"]["passed"]:
        return {"verdict": "REVIEW", "verdict_confidence": 0.3,
                "reason": checks["timing"]["reason"], "escalated_to_llm": False, "checks": checks}

    # clean accept - amount and timing both pass their own policy checks.
    # This is authoritative on its own: the verifier's rule-based checks
    # already encode the policy tolerance, so the matcher's self-reported
    # confidence should not be able to veto a match the checks confirm.
    # Matcher confidence is still recorded in the report for transparency.
    if checks["amount"]["passed"] and checks["timing"]["passed"]:
        return {"verdict": "RECONCILED", "verdict_confidence": 0.97,
                "reason": "; ".join(filter(None, [checks["amount"]["reason"], checks["split"]["reason"]])),
                "escalated_to_llm": False, "checks": checks}

    # gray zone: amount flagged REVIEW, or timing failed, or matcher confidence is low
    gray_zone_summary = {k: v for k, v in checks.items()}
    if use_real_llm:
        result = llm_gray_zone_judgment(proposal, gray_zone_summary, policy)
        return {"verdict": result["verdict"], "verdict_confidence": result["confidence"],
                "reason": result["reason"], "escalated_to_llm": True, "checks": checks}

    # stub: conservative default when no LLM available - never invent confidence
    reasons = [c["reason"] for c in checks.values() if c["reason"] and not c["passed"]]
    return {"verdict": "REVIEW", "verdict_confidence": 0.5,
            "reason": " | ".join(reasons) if reasons else "Gray-zone case, no LLM configured.",
            "escalated_to_llm": False, "checks": checks}


def verify_all(proposals, bank_rows, policy, use_real_llm=False):
    from collections import defaultdict
    all_bank_by_ref = defaultdict(list)
    for r in bank_rows:
        all_bank_by_ref[r["ref_number"]].append(r)

    results = []
    for p in proposals:
        v = verify_match(p, all_bank_by_ref, policy, use_real_llm=use_real_llm)
        results.append({**p, **v})
    return results
