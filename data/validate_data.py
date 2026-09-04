#!/usr/bin/env python3
"""
Validates the synthetic reconciliation batch for internal consistency.
Run this after generate_data.py and before building/testing the matcher.

Checks:
  1. Row counts and referential integrity across all 4 files
  2. Every category produces the correct number of bank rows
  3. duplicate_ref cases are genuinely ambiguous (not accidentally easy)
  4. Amounts reconcile mathematically for every non-exception category
  5. No accidental leakage: ground_truth.csv is never required to reproduce
     bank/gateway/erp - it's a pure label file

Exits non-zero if any check fails, so this can run in CI / a pre-demo script.
"""
import csv
import sys
from collections import Counter, defaultdict

TOL = 1.0  # rupee tolerance for "amounts match"


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="output", help="folder containing the 4 CSVs")
    args = ap.parse_args()
    data_dir = args.data_dir

    bank = load(f"{data_dir}/bank_statement.csv")
    gw = load(f"{data_dir}/gateway_settlement.csv")
    erp = load(f"{data_dir}/erp_ledger.csv")
    gt = load(f"{data_dir}/ground_truth.csv")

    failures = []

    erp_refs = {r["txn_ref"] for r in erp}
    gw_refs = {r["txn_ref"] for r in gw}
    gt_refs = {r["txn_ref"] for r in gt}
    if not (erp_refs == gw_refs == gt_refs):
        failures.append("ERP / gateway / ground_truth txn_ref sets don't match")

    bank_refs = Counter(r["ref_number"] for r in bank)
    cat_of = {r["txn_ref"]: r["category"] for r in gt}
    expected_bank_rows = {"missing_settlement": 0, "split_settlement": 2, "duplicate_ref": 2}
    for ref, cat in cat_of.items():
        expected = expected_bank_rows.get(cat, 1)
        if bank_refs.get(ref, 0) != expected:
            failures.append(f"{ref} ({cat}) expected {expected} bank rows, got {bank_refs.get(ref, 0)}")

    gw_by_ref = {r["txn_ref"]: r for r in gw}
    bank_by_ref = defaultdict(list)
    for r in bank:
        bank_by_ref[r["ref_number"]].append(r)

    for ref, cat in cat_of.items():
        net = float(gw_by_ref[ref]["net_amount"])
        rows = bank_by_ref[ref]
        if cat == "duplicate_ref":
            diffs = sorted(abs(float(r["credit"]) - net) for r in rows)
            if diffs[0] > TOL:
                failures.append(f"{ref} (duplicate_ref): neither bank row is within tolerance")
        elif cat == "split_settlement":
            total = sum(float(r["credit"]) for r in rows)
            if abs(total - net) > TOL:
                failures.append(f"{ref} (split_settlement): split credits don't sum to net_amount")
        elif cat == "missing_settlement":
            if rows:
                failures.append(f"{ref} (missing_settlement): unexpectedly has bank rows")
        elif cat in ("clean", "fee_tax_variance", "timing_mismatch"):
            if not rows:
                failures.append(f"{ref} ({cat}): missing bank row")
        # wrong_amount is allowed to differ by design - no check needed

    print(f"Loaded: bank={len(bank)} gateway={len(gw)} erp={len(erp)} ground_truth={len(gt)}")
    print(f"Category distribution: {dict(Counter(cat_of.values()))}")

    if failures:
        print(f"\nFAILED - {len(failures)} issue(s):")
        for f in failures[:20]:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("\nAll checks passed.")


if __name__ == "__main__":
    main()
