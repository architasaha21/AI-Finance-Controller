# Task Brief: Finance Controller — Remaining Build Tasks

## Project context (read this first)

Repo root: `razorpay buildathon/`

```
razorpay buildathon/
├── .env                          # GROQ_API_KEY, GROQ_MODEL
├── data/
│   ├── generate_data.py          # synthetic data generator (500 txns, seed 42)
│   ├── validate_data.py          # integrity checker
│   └── output/
│       ├── bank_statement.csv    # fields: bank_id, date, description, ref_number, credit, debit
│       ├── gateway_settlement.csv # fields: settlement_id, txn_ref, gross_amount, fee, tax, refund, net_amount, settled_date
│       ├── erp_ledger.csv        # fields: entry_id, txn_ref, amount, entry_date, account_code
│       └── ground_truth.csv      # HIDDEN from the pipeline - only used by metrics.py
├── agents/
│   ├── policy.json               # tolerances: max_timing_diff_days, amount_tolerance_rupees, etc.
│   ├── matcher.py                # deterministic pass + LLM fallback for ambiguous cases
│   ├── verifier.py               # adversarial verifier, policy-check-first then LLM for gray zone
│   └── pipeline.py               # orchestrates matcher -> verifier -> writes CSVs + audit_trail.json
└── report/
    ├── metrics.py                # scores pipeline output against ground_truth.csv
    └── output/
        ├── reconciled.csv
        ├── review_queue.csv
        ├── exceptions.csv
        ├── audit_trail.json      # full per-transaction detail: matcher reasoning + verifier reasoning + check results
        └── metrics_summary.json
```

Known-good baseline (stub/heuristic mode, no LLM): **98.6% match rate vs ground truth, 0 dangerous false positives** (a "dangerous false positive" = something the system marked RECONCILED that should have been REVIEW or EXCEPTION).

`pipeline.py` currently uses a custom shim (`install_groq_client_shim()`) that makes `import anthropic` transparently route to Groq's OpenAI-compatible chat completions endpoint. `use_real_llm` is auto-enabled whenever `GROQ_API_KEY` is present in the environment/`.env`.

---

## TASK 1 — Finish the Groq real-LLM pipeline and verify results

**Goal:** get the pipeline running end-to-end with real Groq LLM calls (not the heuristic stub) for the ambiguous ~13% of cases, and confirm the accuracy numbers still hold up.

**Steps:**

1. Confirm which Groq models are currently live on this account. Run:
   ```
   python debug_groq.py
   ```
   Then separately check the model list — if `/models` succeeded, the response body from that call (not currently printed, so add a `print(resp.read())` temporarily if needed) lists valid model IDs. Cross-check against `.env`'s `GROQ_MODEL` value. `llama-3.1-70b-versatile` is likely decommissioned; `llama-3.3-70b-versatile` is the known-good fallback as of now, but confirm against the live list rather than assuming.

2. Set the confirmed model in `.env`:
   ```
   GROQ_MODEL=<confirmed-live-model-id>
   ```

3. **Before re-running with real LLM, snapshot the current stub-mode results** so we can compare before/after (this comparison itself is a good thing to show judges):
   ```
   mkdir report/output_stub_baseline
   copy report\output\*.csv report\output_stub_baseline\
   copy report\output\*.json report\output_stub_baseline\
   ```

4. Run the real pipeline:
   ```
   cd agents
   python pipeline.py --data ..\data\output --policy policy.json --outdir ..\report\output
   ```
   **Acceptance check:** console output must show `Verifier: N case(s) escalated to LLM for gray-zone judgment` with **N > 0**. If N is 0, `use_real_llm` isn't being picked up — check that `GROQ_API_KEY` is actually loaded (add a debug print of `bool(os.environ.get("GROQ_API_KEY"))` right after `load_env_file()` runs).

5. If any transaction fails with a Groq API error, the improved error handling in `install_groq_client_shim()` should now raise a `RuntimeError` with the actual response body included — capture and read this message before attempting further fixes. Do not silently retry or catch-and-ignore this error; surface it.

6. Re-score against ground truth:
   ```
   cd ..\report
   python metrics.py --ground-truth ..\data\output\ground_truth.csv --report ..\report\output
   ```

7. **Compare against the stub baseline snapshot from step 3.** Specifically check:
   - Did match rate go up, down, or stay flat vs the 98.6% stub baseline?
   - Did "dangerous false positives" stay at 0? If this number increases, that is a regression and must be investigated before moving to Task 2 — a real LLM introducing a dangerous false positive is worse than the stub's more conservative behavior.
   - Which specific `txn_ref`s changed verdict between stub and real-LLM runs? (Diff `report/output_stub_baseline/*.csv` against `report/output/*.csv` on the `txn_ref` + `verifier_verdict` columns.)

**Definition of done:** pipeline runs clean with `escalated_to_llm > 0`, `metrics.py` output captured, dangerous-false-positive count confirmed still 0 (or any increase explicitly investigated and explained), and a short written note (a few sentences, can go in the README later) on how real-LLM results compared to the stub baseline.

---

## TASK 2 — Data adapter abstraction

**Goal:** decouple the matcher/verifier from "where the data came from" so the architecture is genuinely pluggable — this is what lets you truthfully say the system works with Razorpay's data shape without requiring a live API call to be working during the demo.

**Why this matters:** right now `matcher.load_data()` reads 3 specific CSVs directly. We want a layer in between that any data source (CSV, Razorpay API, another gateway) normalizes into, so `matcher.py`/`verifier.py` never change regardless of source.

**Steps:**

1. Create `agents/adapters/` folder with three files:

   **`agents/adapters/schema.py`** — defines the canonical internal format as plain documentation/type hints (no new logic, just makes the contract explicit):
   ```python
   """
   Canonical internal schema every adapter must produce. This is exactly
   the format matcher.py's load_data() currently returns - the adapter
   layer's job is to make this format the ONLY thing matcher.py depends on.

   bank_row:    {bank_id, date (ISO 'YYYY-MM-DD'), description, ref_number, credit (float), debit (float)}
   gateway_row: {settlement_id, txn_ref, gross_amount, fee, tax, refund, net_amount, settled_date (ISO)}
   erp_row:     {entry_id, txn_ref, amount, entry_date (ISO), account_code}
   """
   ```

   **`agents/adapters/csv_adapter.py`** — thin wrapper proving the abstraction doesn't break the existing flow (this should be nearly a pass-through of the existing `load_data` logic in `matcher.py`):
   ```python
   import csv
   import os

   def normalize_source(data_dir):
       """CSV adapter - reads the 3 CSVs and returns them already in
       canonical schema (this is the existing format, so no transformation
       needed, just centralizes the loading logic here instead of matcher.py)."""
       def load(path):
           with open(path, newline="", encoding="utf-8") as f:
               return list(csv.DictReader(f))
       bank = load(os.path.join(data_dir, "bank_statement.csv"))
       gateway = load(os.path.join(data_dir, "gateway_settlement.csv"))
       erp = load(os.path.join(data_dir, "erp_ledger.csv"))
       return bank, gateway, erp
   ```

   **`agents/adapters/razorpay_adapter.py`** — stub with clear field-mapping structure, NOT required to make a live call for this task:
   ```python
   """
   Razorpay adapter - maps Razorpay's Payments + Settlements API response
   shape into the canonical schema. This does NOT need to be wired to a
   live API call to complete this task - the goal is a correct, honest
   mapping function that CAN be pointed at live data later.

   Look up the current field names in Razorpay's API docs before filling
   in the mapping (do not guess field names from memory - verify against
   https://razorpay.com/docs/api/payments/ and
   https://razorpay.com/docs/api/settlements/ since API shapes change).

   Razorpay does not have a literal "bank statement" concept in its API -
   the closest equivalent is the Settlements API's individual settlement
   records, which show what actually got paid out. Decide during
   implementation whether Razorpay data maps to (bank + gateway) as two
   separate normalized outputs, or collapses into a simplified 2-source
   model (gateway + ERP only, with bank_row derived from settlement
   payout records). Document whichever decision is made directly in this
   file's docstring - do not leave it implicit.
   """

   def normalize_source(razorpay_client, from_date, to_date):
       """
       TODO: implement once Razorpay test-mode API access is confirmed working.
       Must return (bank_rows, gateway_rows, erp_rows) in the exact schema
       defined in schema.py - this is the only contract that matters.
       """
       raise NotImplementedError(
           "Razorpay adapter not yet wired to live API - see schema.py "
           "for the exact output format required."
       )
   ```

2. Update `agents/matcher.py`'s `load_data()` to delegate to `adapters/csv_adapter.py` instead of containing the CSV-reading logic directly:
   ```python
   from adapters.csv_adapter import normalize_source as load_csv_source

   def load_data(data_dir):
       return load_csv_source(data_dir)
   ```

3. Add a `--source` flag to `pipeline.py` (default `csv`) that selects which adapter to use. For this task, only `csv` needs to actually work — `razorpay` should be a recognized-but-not-yet-functional option that raises the `NotImplementedError` from the stub, not a silent failure or a crash with a confusing traceback.

**Acceptance check:** run the exact same command from Task 1 step 4 again. Output must be byte-for-byte identical to before this refactor (same verdict counts, same audit trail) — this refactor must not change any behavior, only restructure where the CSV-reading code lives. If numbers changed, the refactor introduced a bug; revert and redo.

**Definition of done:** `agents/adapters/` folder exists with all 3 files, `matcher.py` delegates to it, pipeline still produces identical output to the pre-refactor baseline, and `razorpay_adapter.py` has an honest, documented (not fabricated) field-mapping plan even though it's not live yet.

---

## TASK 3 — Streamlit dashboard

**Goal:** the single highest-leverage remaining piece. This is what judges actually look at and remember — prioritize this over everything except Task 1.

**Setup:**
```
pip install streamlit pandas
mkdir dashboard
```
Create `dashboard/app.py`.

**Data sources for the dashboard (read-only, never write back):**
- `report/output/reconciled.csv`, `review_queue.csv`, `exceptions.csv`
- `report/output/audit_trail.json` (the detail view's main data source)
- `agents/policy.json` (for the policy panel)
- `report/output/metrics_summary.json` (for the summary KPIs, if Task 1's `metrics.py` run has been done — if not present yet, the dashboard should degrade gracefully, not crash: show "run metrics.py to see accuracy stats" instead of the KPI cards)

Build in **this exact order** — each section should be a working, demoable increment before moving to the next one, not built all at once and debugged together:

### 3a. Batch summary (build first)
- Use `st.set_page_config(layout="wide")` and a clear title, e.g. "Finance Controller — Reconciliation Batch"
- Row of `st.metric()` KPI cards: Total transactions processed, % RECONCILED, % REVIEW, % EXCEPTION, % resolved deterministically (no LLM needed) vs % that needed LLM reasoning
- If `metrics_summary.json` exists: additional row with Match rate vs ground truth, Dangerous false positives (make this one visually distinct — e.g. a colored `st.metric` with delta, since this is the single most important safety number per the earlier design discussion)
- Small bar chart (verdict counts) using `st.bar_chart`

**Acceptance check:** `streamlit run dashboard/app.py` shows the summary page with real numbers matching what `pipeline.py`'s console output showed, no crashes if `metrics_summary.json` is missing.

### 3b. Exception & review queue
- Load `review_queue.csv` and `exceptions.csv` into a combined `st.dataframe`, with a filter (`st.selectbox` or `st.multiselect`) to switch between "Review", "Exception", or "Both"
- Default view should show REVIEW + EXCEPTION only, not RECONCILED (the point is surfacing what needs attention, not re-displaying the 87% that resolved cleanly)
- Columns to show: `txn_ref`, `verifier_verdict`, `reason`, `matcher_confidence`, `verifier_confidence`, `escalated_to_llm`
- Sort by verdict then by confidence ascending (lowest-confidence / most-uncertain cases surfaced first — this is genuinely useful triage behavior, not just a display choice)

**Acceptance check:** table renders, filtering works, row count matches the CSV row counts exactly.

### 3c. Click-through detail / audit trail view
- Add a `st.selectbox` (or make table rows clickable via `st.dataframe` selection, whichever is simpler to implement reliably) to pick a `txn_ref`
- Load that transaction's full record from `audit_trail.json` and render it as a clear **before/after narrative**, not a raw JSON dump:
  ```
  Transaction: TXN100234
  ERP amount: ₹12,500.00        Gateway net: ₹12,498.50

  🔍 MATCHER
     Method: llm
     Proposed: [BNK00234]
     Confidence: 0.65
     Reasoning: "<matcher's reasoning text>"

  ⚖️ VERIFIER
     Checks run:
       identity: <pass/fail + reason>
       amount:   <pass/fail + reason>
       timing:   <pass/fail + reason>
       split:    <pass/fail + reason>
     Verdict: REVIEW
     Escalated to LLM: True
     Reasoning: "<verifier's reasoning text>"
  ```
- Use `st.columns(2)` to put Matcher and Verifier side by side visually — this is the single most important visual moment in the whole dashboard, since it's the literal proof of "one AI proposes, another tries to disprove it." Do not compress this into a single paragraph of text; the two-column separation is what makes the adversarial structure visually obvious without narration.
- Use color/icons for verdict (🟢 RECONCILED, 🟡 REVIEW, 🔴 EXCEPTION) consistently across the whole dashboard, not just this view.

**Acceptance check:** selecting any `txn_ref` from the dropdown correctly loads and displays that transaction's full matcher + verifier detail with no missing fields or crashes on edge cases (e.g., a transaction with 0 or 2 proposed bank IDs).

### 3d. Policy panel
- Read `agents/policy.json` and render its tolerances as a clean read-only table or a set of labeled `st.metric`/`st.text` rows (skip the `_comments` key from display, or show it as `st.caption` help text)
- Put this in a sidebar (`st.sidebar`) or a collapsible `st.expander` — it's supporting context, not the main event, so it shouldn't compete for primary visual space with 3a-3c

**Definition of done for Task 3 overall:** all four sections working, `streamlit run dashboard/app.py` runs without errors on a fresh pipeline output, and the detail view (3c) specifically has been visually checked to clearly separate matcher vs verifier reasoning.

---

## TASK 4 — Find and rehearse the hero demo case

**Goal:** identify one specific, real transaction (not hypothetical) where the verifier caught a problem the matcher proposed — this is the single moment that should anchor the live pitch.

**Steps:**

1. Write a small one-off helper script `scripts/find_demo_case.py`:
   ```python
   import json

   with open("report/output/audit_trail.json", encoding="utf-8") as f:
       audit = json.load(f)

   # Best candidates: matcher proposed something with decent confidence,
   # verifier rejected or flagged it with a specific, explainable reason -
   # duplicate reference and wrong-amount cases make the clearest story.
   candidates = [
       a for a in audit
       if a["verifier"]["verdict"] in ("REVIEW", "EXCEPTION")
       and a["matcher"]["confidence"] >= 0.5
       and a["verifier"]["checks"].get("identity") is not None
   ]

   for c in candidates[:10]:
       print(f"\n{c['txn_ref']}  matcher_conf={c['matcher']['confidence']}  verdict={c['verifier']['verdict']}")
       print(f"  matcher said: {c['matcher']['reasoning']}")
       print(f"  verifier said: {c['verifier']['reason']}")
   ```
   Run it: `python scripts\find_demo_case.py`

2. From the printed candidates, manually pick the ONE case with the clearest, most explainable story — ideally a duplicate reference case (easiest for a non-technical judge to immediately understand: "same reference number used twice, verifier caught it") over a subtler amount-variance case.

3. Note that `txn_ref` down somewhere you'll have it handy during the live demo (not something to search for on stage).

4. Rehearse the exact click path in the dashboard to reach that transaction's detail view, and time the full explanation out loud — target under 60 seconds: "the matcher proposed this match with X% confidence, but the verifier checked and found [specific reason], so it correctly flagged this for human review instead of silently accepting it."

**Definition of done:** one specific `txn_ref` identified and written down, the click path to it in the dashboard rehearsed at least twice, spoken explanation timed under 60 seconds.

---

## Priority order if time runs short

If not all 4 tasks finish: **Task 1 > Task 3 (sections 3a-3c only, skip 3d if needed) > Task 4 > Task 2.**

Task 2 (the adapter) is architecturally correct and worth having, but it changes nothing the judges can see directly — if time is genuinely tight, it's the one to cut or leave partially done. Tasks 1, 3, and 4 are what's actually visible in the demo.
