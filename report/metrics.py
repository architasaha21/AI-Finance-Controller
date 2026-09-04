#!/usr/bin/env python3
"""
Scores pipeline output against the hidden ground truth. This is the ONLY
script that touches ground_truth.csv - the matcher and verifier never see
it, and never should. Run this after pipeline.py.

Usage:
  python3 metrics.py --ground-truth ../data/output/ground_truth.csv --report ../report/output

Prints a confusion matrix, per-class precision/recall, and flags the one
number that matters most for a finance system: how many EXCEPTION or
REVIEW cases got silently marked RECONCILED (a false positive is far more
dangerous than an unnecessary review - a wrong "reconciled" hides a real
problem, a wrong "review" just costs someone five minutes).
"""
import argparse
import csv
import json
import os
from collections import Counter, defaultdict

STATUSES = ["RECONCILED", "REVIEW", "EXCEPTION"]


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_ground_truth(path):
    return {r["txn_ref"]: r["expected_status"] for r in load_csv(path)}, \
           {r["txn_ref"]: r["category"] for r in load_csv(path)}


def load_actual(report_dir):
    actual = {}
    for fname, status in [("reconciled.csv", "RECONCILED"),
                           ("review_queue.csv", "REVIEW"),
                           ("exceptions.csv", "EXCEPTION")]:
        path = os.path.join(report_dir, fname)
        if not os.path.exists(path):
            continue
        for r in load_csv(path):
            actual[r["txn_ref"]] = status
    return actual


def confusion_matrix(expected, actual):
    matrix = {e: Counter() for e in STATUSES}
    for ref, exp in expected.items():
        matrix[exp][actual.get(ref, "MISSING")] += 1
    return matrix


def precision_recall(matrix):
    results = {}
    for status in STATUSES:
        tp = matrix[status][status]
        fn = sum(matrix[status][s] for s in STATUSES if s != status) + matrix[status]["MISSING"]
        fp = sum(matrix[other][status] for other in STATUSES if other != status)
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        results[status] = {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn}
    return results


def print_matrix(matrix):
    print(f"{'expected \\ actual':20s}" + "".join(f"{s:>12s}" for s in STATUSES) + f"{'MISSING':>10s}")
    for exp in STATUSES:
        row = matrix[exp]
        print(f"{exp:20s}" + "".join(f"{row[s]:>12d}" for s in STATUSES) + f"{row['MISSING']:>10d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ground-truth", default="../data/output/ground_truth.csv")
    ap.add_argument("--report", default="../report/output")
    args = ap.parse_args()

    expected, category = load_ground_truth(args.ground_truth)
    actual = load_actual(args.report)

    matrix = confusion_matrix(expected, actual)
    print("=== CONFUSION MATRIX ===")
    print_matrix(matrix)

    pr = precision_recall(matrix)
    print("\n=== PER-CLASS PRECISION / RECALL ===")
    for status in STATUSES:
        p, r = pr[status]["precision"], pr[status]["recall"]
        print(f"  {status:12s} precision={p:.1%}  recall={r:.1%}  "
              f"(tp={pr[status]['tp']} fp={pr[status]['fp']} fn={pr[status]['fn']})")

    total = len(expected)
    correct = sum(1 for ref, exp in expected.items() if actual.get(ref) == exp)
    print(f"\n=== OVERALL ===")
    print(f"  Match rate (agrees with ground truth): {correct}/{total} ({correct/total:.1%})")

    # the number that actually matters for a finance system
    dangerous = [(ref, expected[ref], actual.get(ref, "MISSING"), category[ref])
                 for ref in expected
                 if expected[ref] in ("REVIEW", "EXCEPTION") and actual.get(ref) == "RECONCILED"]
    print(f"\n=== DANGEROUS FALSE POSITIVES ===")
    print(f"  Cases that should have been REVIEW/EXCEPTION but were auto-marked RECONCILED: "
          f"{len(dangerous)}")
    if dangerous:
        print("  (this is the single most important number to report - a false RECONCILED")
        print("   hides a real problem, worse than an unnecessary REVIEW)")
        for ref, exp, act, cat in dangerous[:10]:
            print(f"    {ref}  expected={exp}  got={act}  category={cat}")
    else:
        print("  None. Zero dangerous false positives on this batch.")

    # mismatches broken down by injected failure category - useful for
    # spotting whether a specific category is the pipeline's weak point
    print(f"\n=== MISMATCHES BY CATEGORY ===")
    mismatch_by_cat = Counter()
    total_by_cat = Counter()
    for ref, exp in expected.items():
        total_by_cat[category[ref]] += 1
        if actual.get(ref) != exp:
            mismatch_by_cat[category[ref]] += 1
    for cat in sorted(total_by_cat, key=lambda c: -mismatch_by_cat[c]):
        n_wrong, n_total = mismatch_by_cat[cat], total_by_cat[cat]
        print(f"  {cat:20s} {n_wrong}/{n_total} wrong ({n_wrong/n_total:.0%})")

    summary = {
        "total_records": total,
        "match_rate": correct / total,
        "confusion_matrix": {e: dict(matrix[e]) for e in STATUSES},
        "precision_recall": pr,
        "dangerous_false_positives": len(dangerous),
        "mismatches_by_category": dict(mismatch_by_cat),
    }
    out_path = os.path.join(args.report, "metrics_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
