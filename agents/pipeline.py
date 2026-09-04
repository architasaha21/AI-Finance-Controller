#!/usr/bin/env python3
"""
Runs the full reconciliation pipeline: matcher -> verifier -> report.

Usage:
  python3 pipeline.py --data ../data/output --policy policy.json --outdir ../report/output

Writes three CSVs + one JSON audit trail:
  reconciled.csv     - RECONCILED verdicts
  review_queue.csv   - REVIEW verdicts (needs a human)
  exceptions.csv     - EXCEPTION verdicts
  audit_trail.json   - full detail per txn_ref, including every check the
                        verifier ran and why - this is what you drill into
                        during the demo to show "the verifier caught a false match"
"""
import argparse
import csv
import json
import os
import sys

from matcher import run_matcher, load_data
from verifier import verify_all


def load_env_file(path):
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


def install_groq_client_shim():
    if "groq" in sys.modules:
        return

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return

    import types
    import urllib.request
    import urllib.error

    class _GroqContent:
        def __init__(self, text):
            self.text = text

    class _GroqResponse:
        def __init__(self, text):
            self.content = [_GroqContent(text)]

    class _GroqMessages:
        def create(self, model, max_tokens, messages):
            import time
            import re
            payload = {
                "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                "messages": messages,
                "max_tokens": 4096,
            }
            max_retries = 25
            for attempt in range(max_retries):
                request = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (compatible; recon-agent/1.0)",
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        data = json.loads(response.read().decode("utf-8"))
                        break
                except urllib.error.HTTPError as e:
                    body = e.read().decode("utf-8")
                    if e.code == 429:
                        # Exponential backoff default
                        wait_time = 2.0 * (1.5 ** attempt)
                        # Try parsing headers
                        retry_after = e.headers.get("retry-after") or e.headers.get("Retry-After")
                        if retry_after:
                            try:
                                wait_time = float(retry_after) + 0.5
                            except ValueError:
                                pass
                        else:
                            match = re.search(r"try again in (\d+(?:\.\d+)?)s", body)
                            if match:
                                wait_time = float(match.group(1)) + 0.5
                            else:
                                match_min = re.search(r"try again in (\d+)m(\d+(?:\.\d+)?)s", body)
                                if match_min:
                                    wait_time = int(match_min.group(1)) * 60 + float(match_min.group(2)) + 0.5
                        print(f"Rate limited (429). Body: {body.strip()}")
                        print(f"Retrying in {wait_time:.2f} seconds (Attempt {attempt+1}/{max_retries})...")
                        time.sleep(wait_time)
                        continue
                    print(f"DEBUG: Failed request payload size {len(json.dumps(payload))}, content: {json.dumps(payload)}")
                    raise RuntimeError(
                        f"Groq API returned {e.code} for model "
                        f"'{payload['model']}'. Response body: {body}"
                    ) from None
                except Exception as ex:
                    print(f"DEBUG: Exception: {ex}, payload: {json.dumps(payload)}")
                    raise ex
            else:
                raise RuntimeError(f"Failed after {max_retries} retries due to rate limits.")

            text = data["choices"][0]["message"]["content"]
            if "<think>" in text:
                if "</think>" in text:
                    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
                else:
                    # If truncated/unfinished think block
                    parts = text.split("</think>")
                    text = parts[-1].strip()

            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start:end+1]

            print(f"DEBUG: parsed text content: {repr(text)}".encode('ascii', errors='replace').decode('ascii'))
            return _GroqResponse(text)

    class Groq:
        def __init__(self, api_key=None):
            self.messages = _GroqMessages()

    shim = types.ModuleType("groq")
    shim.Groq = Groq
    shim.Anthropic = Groq
    sys.modules["groq"] = shim
    sys.modules["anthropic"] = shim


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="../data/output")
    ap.add_argument("--policy", default="policy.json")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--source", default="csv", choices=["csv", "razorpay"], help="Select data source adapter")
    ap.add_argument("--no-llm", action="store_true", help="Use deterministic/heuristic fallback even when .env contains GROQ_API_KEY")
    args = ap.parse_args()

    # Default outdir: separate folder for razorpay so results never mix
    if args.outdir is None:
        args.outdir = "../report/output_razorpay" if args.source == "razorpay" else "../report/output"

    load_env_file(os.path.join(os.path.dirname(__file__), "..", ".env"))
    install_groq_client_shim()

    use_real_llm = bool(os.environ.get("GROQ_API_KEY")) and not args.no_llm
    print("=== MATCHER ===")
    proposals, policy = run_matcher(args.data, args.policy, use_real_llm=use_real_llm, source=args.source)

    print("\n=== VERIFIER ===")
    bank_rows, _, _ = load_data(args.data, source=args.source)
    results = verify_all(proposals, bank_rows, policy, use_real_llm=use_real_llm)

    escalated = sum(1 for r in results if r["escalated_to_llm"])
    print(f"Verifier: {escalated} case(s) escalated to LLM for gray-zone judgment "
          f"({escalated/len(results)*100:.0f}%)")

    verdict_counts = {"RECONCILED": 0, "REVIEW": 0, "EXCEPTION": 0}
    for r in results:
        verdict_counts[r["verdict"]] += 1

    print(f"\n=== FINAL RESULT ===")
    total = len(results)
    for v, c in verdict_counts.items():
        print(f"  {v:12s} {c:4d}  ({c/total*100:.1f}%)")

    os.makedirs(args.outdir, exist_ok=True)

    def flat_row(r):
        return {
            "txn_ref": r["txn_ref"],
            "proposed_bank_ids": ";".join(r["proposed_bank_ids"]),
            "matcher_method": r["method"],
            "matcher_confidence": round(r["confidence"], 2),
            "verifier_verdict": r["verdict"],
            "verifier_confidence": round(r["verdict_confidence"], 2),
            "reason": r["reason"],
            "escalated_to_llm": r["escalated_to_llm"],
        }

    fieldnames = ["txn_ref", "proposed_bank_ids", "matcher_method", "matcher_confidence",
                  "verifier_verdict", "verifier_confidence", "reason", "escalated_to_llm"]

    reconciled = [flat_row(r) for r in results if r["verdict"] == "RECONCILED"]
    review = [flat_row(r) for r in results if r["verdict"] == "REVIEW"]
    exceptions = [flat_row(r) for r in results if r["verdict"] == "EXCEPTION"]

    write_csv(os.path.join(args.outdir, "reconciled.csv"), reconciled, fieldnames)
    write_csv(os.path.join(args.outdir, "review_queue.csv"), review, fieldnames)
    write_csv(os.path.join(args.outdir, "exceptions.csv"), exceptions, fieldnames)

    audit = []
    for r in results:
        audit.append({
            "txn_ref": r["txn_ref"],
            "erp_amount": r["erp_row"]["amount"],
            "gateway_net": r["gw_row"]["net_amount"],
            "candidates": [c["bank_id"] for c in r["candidates"]],
            "matcher": {"method": r["method"], "confidence": r["confidence"],
                        "reasoning": r["reasoning"], "proposed": r["proposed_bank_ids"]},
            "verifier": {"verdict": r["verdict"], "reason": r["reason"],
                         "confidence": r["verdict_confidence"],
                         "escalated_to_llm": r["escalated_to_llm"],
                         "checks": {k: {"passed": v.get("passed"), "reason": v.get("reason")} for k, v in r["checks"].items()}},
        })
    with open(os.path.join(args.outdir, "audit_trail.json"), "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, default=str)

    print(f"\nWrote reconciled.csv ({len(reconciled)}), review_queue.csv ({len(review)}), "
          f"exceptions.csv ({len(exceptions)}), audit_trail.json to {args.outdir}")


if __name__ == "__main__":
    main()