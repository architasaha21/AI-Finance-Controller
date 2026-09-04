# RazorRecon Finance Control Tower

### Run the books. Protect the cash position.

RazorRecon is an adversarial finance-operations controller built for the Razorpay AI Buildathon. It reconciles bank credits, payment-gateway settlements, and ERP entries across a full transaction batch, then separates safe matches from cases that require human judgment.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Razorpay](https://img.shields.io/badge/Razorpay-Test%20Mode-0C2E8A)
![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B)
![Groq](https://img.shields.io/badge/Groq-LLM%20Reasoning-F55036)
![Safety](https://img.shields.io/badge/Dangerous%20False%20Positives-0-2EA44F)

## Why This Matters

The finance-ops bottleneck is not producing a match quickly; it is verifying that the match is safe. RazorRecon uses two separate decision stages:

- **Matcher:** resolves obvious records deterministically using reference, amount, and timing rules, then sends ambiguous cases to LLM reasoning.
- **Verifier:** independently tries to disprove each proposal using policy checks for timing, amount variance, duplicate references, missing settlements, and split settlements.

The system is intentionally conservative: an uncertain transaction goes to a human instead of being silently marked reconciled.

## Track Fit and Measured Result

The included synthetic batch contains **500 transactions** across bank, gateway, and ERP sources, with injected timing mismatches, duplicate references, missing settlements, fee/tax variance, split settlements, and wrong amounts.

| Measure | Result |
| --- | ---: |
| Agreement with hidden ground truth | **500/500 (100%)** |
| Reconciled automatically | 440 |
| Sent for human review | 49 |
| Exceptions | 11 |
| Dangerous false positives | **0** |

This demonstrates the complete finance-ops loop: process a meaningful batch, quantify accuracy, and expose an honest exception list rather than hiding unresolved records.

## Architecture

```text
Bank Statement CSV / Razorpay Payments / ERP Ledger
			 |
			 v
		 Source Adapter Layer
			 |
			 v
	      Deterministic Matcher Agent
		    |              |
	     clear matches     ambiguous cases
		    |              v
		    |        LLM reasoning
		    |              |
		    +-------> Adversarial Verifier
				   |
		 +-----------------+------------------+
		 v                 v                  v
	    RECONCILED          REVIEW             EXCEPTION
			      Human decision log
				   |
			 Streamlit Control Tower
```

## What the Dashboard Shows

- Batch-level reconciliation and safety KPIs
- Deterministic versus LLM-assisted resolution
- Review and exception queues sorted for triage
- Side-by-side Matcher proposal and Verifier decision
- Per-transaction policy checks and reasoning
- Approve, reject, and investigate actions with persisted decisions
- Policy tolerance reference and replay view for demos

## Quick Start

Use the included synthetic 500-transaction batch for a deterministic smoke test:

```powershell
python data\validate_data.py
python agents\pipeline.py --data data\output --policy agents\policy.json --outdir report\output --no-llm
python report\metrics.py --ground-truth data\output\ground_truth.csv --report report\output
```

The expected result is 500/500 agreement with ground truth and zero dangerous false positives.

## Razorpay Test-Mode Integration

Copy `.env.example` to `.env`, then set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` to test-mode credentials from the Razorpay Dashboard. Run:

```powershell
python agents\pipeline.py --source razorpay --policy agents\policy.json --outdir report\output_razorpay --no-llm
```

The adapter fetches captured test-mode payments and maps payment fields into the canonical gateway and ERP rows. Razorpay does not provide the merchant bank statement through this API, so the adapter generates clearly labeled simulated bank rows from settlement net amounts and plants one mismatch for verifier demonstration. A production deployment should replace that simulated bank feed with a real bank statement adapter.

Razorpay test-mode payments are fetched through the live adapter. Because Razorpay does not expose the merchant bank statement through the Payments API, the demo explicitly simulates the bank side from settlement net amounts and plants one mismatch for verifier demonstration. Replace that simulated source with a real bank-statement adapter in production.

## Dashboard

```powershell
streamlit run dashboard\app.py
```

Keep API keys in `.env`; never commit that file or paste its contents into a demo or issue.
