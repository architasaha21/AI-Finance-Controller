#!/usr/bin/env python3
"""
Generates a synthetic reconciliation batch for the AI Finance Controller build.

Outputs (all in ./data/):
  bank_statement.csv     - what the bank says was credited
  gateway_settlement.csv - what the payment gateway settled
  erp_ledger.csv          - what the ERP/accounting system recorded
  ground_truth.csv        - HIDDEN answer key: category + expected status per txn_ref
                            (never feed this to the matcher/verifier agents -
                             only use it afterwards to score precision/recall)

Distribution (base = 500 transactions):
  85%  clean               - exact match, no anomaly. Deterministic matcher should catch these.
   6%  timing_mismatch     - settlement lands 2-4 days after entry (borderline vs. policy)
   4%  fee_tax_variance    - net amount requires reasoning through fee+tax, small rounding noise
   2%  duplicate_ref       - same ref_number used on two different bank records (must reject)
   1%  missing_settlement  - ERP has the entry, bank has nothing (true exception)
   1%  split_settlement    - one ERP amount arrives as two separate bank credits
   1%  wrong_amount        - unexplained shortfall beyond any fee/tax/refund (true exception)

Usage:
  python3 generate_data.py --count 500 --seed 42
"""
import argparse
import csv
import os
import random
from datetime import timedelta
from faker import Faker

CATEGORY_WEIGHTS = {
    "clean": 0.85,
    "timing_mismatch": 0.06,
    "fee_tax_variance": 0.04,
    "duplicate_ref": 0.02,
    "missing_settlement": 0.01,
    "split_settlement": 0.01,
    "wrong_amount": 0.01,
}

# expected_status the agent pipeline SHOULD arrive at, per category.
# Note: timing_mismatch and duplicate_ref are graded as REVIEW, not an
# auto-accept/auto-reject - a conservative verifier should escalate both
# to a human rather than silently deciding either way. See policy.json's
# max_timing_diff_days (currently 1 day, stricter than the 2-4 day drift
# injected below) - this is intentional: the point is to test whether the
# system correctly flags what's outside its own stated tolerance.
EXPECTED_STATUS = {
    "clean": "RECONCILED",
    "timing_mismatch": "REVIEW",        # outside policy's 1-day tolerance -> flag, don't auto-accept
    "fee_tax_variance": "RECONCILED",   # fully explained by fee+tax+refund -> verifier should accept
    "duplicate_ref": "REVIEW",          # ambiguous identity -> flag, don't auto-reject or auto-accept
    "missing_settlement": "EXCEPTION",
    "split_settlement": "RECONCILED",   # correctly identified + sum reconciles -> auto-resolve,
                                         # not a forced human review (this is the "fantastic demo
                                         # case": the system explains a split no naive matcher catches)
    "wrong_amount": "EXCEPTION",
}


def build_categories(count, seed):
    rng = random.Random(seed)
    cats = list(CATEGORY_WEIGHTS.keys())
    weights = list(CATEGORY_WEIGHTS.values())
    chosen = rng.choices(cats, weights=weights, k=count)
    return chosen


def money(rng, lo=500, hi=50000):
    return round(rng.uniform(lo, hi), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500, help="number of base transactions")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", default="data")
    args = ap.parse_args()

    fake = Faker()
    Faker.seed(args.seed)
    rng = random.Random(args.seed)

    os.makedirs(args.outdir, exist_ok=True)
    categories = build_categories(args.count, args.seed)

    bank_rows = []
    gateway_rows = []
    erp_rows = []
    ground_truth = []

    bank_id_ctr = 1
    settlement_id_ctr = 1
    entry_id_ctr = 1

    for i, category in enumerate(categories):
        txn_ref = f"TXN{100000 + i}"
        base_date = fake.date_between(start_date="-60d", end_date="-2d")
        gross = money(rng)
        fee_rate = rng.uniform(0.015, 0.025)
        tax_rate = 0.18  # GST on fee, typical India setup
        fee = round(gross * fee_rate, 2)
        tax = round(fee * tax_rate, 2)
        refund = 0.0
        net = round(gross - fee - tax - refund, 2)

        entry_date = base_date
        settled_date = base_date + timedelta(days=1)
        bank_date = settled_date
        bank_amount = net
        notes = ""

        if category == "clean":
            pass  # everything above is already consistent

        elif category == "timing_mismatch":
            drift = rng.randint(2, 4)
            bank_date = base_date + timedelta(days=drift)
            notes = f"settlement landed {drift} days after entry (policy allows 1)"

        elif category == "fee_tax_variance":
            if rng.random() < 0.5:
                # real partial refund, folded exactly into the net calc - fully explainable
                refund = round(gross * rng.uniform(0.01, 0.05), 2)
                net = round(gross - fee - tax - refund, 2)
                bank_amount = net
                notes = f"₹{refund} partial refund included in net settlement"
            else:
                # small unexplained rounding noise on top of the normal fee/tax math
                noise = round(rng.uniform(0.5, 3.0), 2)
                bank_amount = round(net - noise, 2)
                notes = f"₹{noise} rounding variance beyond standard fee+tax calc"

        elif category == "duplicate_ref":
            notes = "same ref_number reused on a second, unrelated bank record"

        elif category == "missing_settlement":
            notes = "ERP entry exists, no corresponding bank record"

        elif category == "split_settlement":
            notes = "single ERP amount arrived as two separate bank credits"

        elif category == "wrong_amount":
            shortfall = round(gross * rng.uniform(0.05, 0.15), 2)
            bank_amount = round(net - shortfall, 2)
            notes = f"₹{shortfall} unexplained shortfall, not covered by fee/tax/refund"

        # --- ERP ledger row (always present) ---
        erp_rows.append({
            "entry_id": f"ERP{entry_id_ctr:05d}",
            "txn_ref": txn_ref,
            "amount": gross,
            "entry_date": entry_date.isoformat(),
            "account_code": rng.choice(["4000-SALES", "4010-SALES-INTL", "4020-SUBSCRIPTIONS"]),
        })
        entry_id_ctr += 1

        # --- Gateway settlement row (always present) ---
        gateway_rows.append({
            "settlement_id": f"STL{settlement_id_ctr:05d}",
            "txn_ref": txn_ref,
            "gross_amount": gross,
            "fee": fee,
            "tax": tax,
            "refund": refund,
            "net_amount": net,
            "settled_date": settled_date.isoformat(),
        })
        settlement_id_ctr += 1

        # --- Bank statement row(s) ---
        if category == "missing_settlement":
            pass  # deliberately no bank row at all

        elif category == "split_settlement":
            half1 = round(bank_amount / 2 + 15, 2)
            half2 = round(bank_amount - half1, 2)
            for part in (half1, half2):
                bank_rows.append({
                    "bank_id": f"BNK{bank_id_ctr:05d}",
                    "date": bank_date.isoformat(),
                    "description": f"NEFT CR {fake.company()[:20]}",
                    "ref_number": txn_ref,
                    "credit": part,
                    "debit": 0.0,
                })
                bank_id_ctr += 1

        elif category == "duplicate_ref":
            # the correct match
            bank_rows.append({
                "bank_id": f"BNK{bank_id_ctr:05d}",
                "date": bank_date.isoformat(),
                "description": f"NEFT CR {fake.company()[:20]}",
                "ref_number": txn_ref,
                "credit": bank_amount,
                "debit": 0.0,
            })
            bank_id_ctr += 1
            # a decoy using the SAME ref_number but wrong amount/date
            bank_rows.append({
                "bank_id": f"BNK{bank_id_ctr:05d}",
                "date": (bank_date + timedelta(days=rng.randint(5, 10))).isoformat(),
                "description": f"NEFT CR {fake.company()[:20]}",
                "ref_number": txn_ref,
                "credit": money(rng),
                "debit": 0.0,
            })
            bank_id_ctr += 1

        else:
            bank_rows.append({
                "bank_id": f"BNK{bank_id_ctr:05d}",
                "date": bank_date.isoformat(),
                "description": f"NEFT CR {fake.company()[:20]}",
                "ref_number": txn_ref,
                "credit": bank_amount,
                "debit": 0.0,
            })
            bank_id_ctr += 1

        ground_truth.append({
            "txn_ref": txn_ref,
            "category": category,
            "expected_status": EXPECTED_STATUS[category],
            "notes": notes,
        })

    rng.shuffle(bank_rows)  # so the matcher can't cheat by assuming row order = txn order

    def write_csv(path, rows, fieldnames):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

    write_csv(os.path.join(args.outdir, "bank_statement.csv"), bank_rows,
              ["bank_id", "date", "description", "ref_number", "credit", "debit"])
    write_csv(os.path.join(args.outdir, "gateway_settlement.csv"), gateway_rows,
              ["settlement_id", "txn_ref", "gross_amount", "fee", "tax", "refund", "net_amount", "settled_date"])
    write_csv(os.path.join(args.outdir, "erp_ledger.csv"), erp_rows,
              ["entry_id", "txn_ref", "amount", "entry_date", "account_code"])
    write_csv(os.path.join(args.outdir, "ground_truth.csv"), ground_truth,
              ["txn_ref", "category", "expected_status", "notes"])

    print(f"Generated {args.count} base transactions -> {len(bank_rows)} bank rows, "
          f"{len(gateway_rows)} settlements, {len(erp_rows)} ledger entries")
    from collections import Counter
    counts = Counter(categories)
    for cat, w in CATEGORY_WEIGHTS.items():
        print(f"  {cat:20s} {counts[cat]:4d}  (target {w*100:.0f}%)")


if __name__ == "__main__":
    main()
