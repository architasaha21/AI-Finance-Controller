import json
import os

def main():
    audit_path = os.path.join("report", "output", "audit_trail.json")
    if not os.path.exists(audit_path):
        print(f"Error: audit_trail.json not found at {audit_path}. Please run pipeline.py first.")
        return

    with open(audit_path, "r", encoding="utf-8") as f:
        audit = json.load(f)

    # Filter for candidates: matcher had decent confidence (>= 0.5), 
    # but the verifier flagged or rejected it (verdict in REVIEW or EXCEPTION).
    # We particularly want cases where identity check failed (duplicate references).
    candidates = [
        a for a in audit
        if a["verifier"]["verdict"] in ("REVIEW", "EXCEPTION")
        and a["matcher"]["confidence"] >= 0.5
        and a["verifier"]["checks"].get("identity") is not None
    ]

    print(f"Found {len(candidates)} candidate hero cases where matcher was confident but verifier flagged/rejected:")
    def safe_print(text):
        print(text.encode('ascii', errors='replace').decode('ascii'))

    for c in candidates[:15]:
        safe_print(f"\nTransaction Ref: {c['txn_ref']}")
        safe_print(f"  Matcher Conf: {c['matcher']['confidence']}  |  Verifier Verdict: {c['verifier']['verdict']}")
        safe_print(f"  Matcher reasoning: {c['matcher']['reasoning']}")
        safe_print(f"  Verifier reasoning: {c['verifier']['reason']}")
        safe_print(f"  Failed Check Details:")
        for k, v in c["verifier"]["checks"].items():
            if v:
                safe_print(f"    - {k}: {v}")

if __name__ == "__main__":
    main()
