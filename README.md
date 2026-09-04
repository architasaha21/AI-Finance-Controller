## AI Finance Controller

An adversarial reconciliation pipeline for bank, payment gateway, and ERP records. The matcher proposes matches; the verifier checks policy rules and sends uncertain cases to review.

### Quick start

Use the included synthetic 500-transaction batch for a deterministic smoke test:

```powershell
python data\validate_data.py
python agents\pipeline.py --data data\output --policy agents\policy.json --outdir report\output --no-llm
python report\metrics.py --ground-truth data\output\ground_truth.csv --report report\output
```

The expected result is 500/500 agreement with ground truth and zero dangerous false positives.

### Razorpay test-mode integration

Copy `.env.example` to `.env`, then set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` to test-mode credentials from the Razorpay Dashboard. Run:

```powershell
python agents\pipeline.py --source razorpay --policy agents\policy.json --outdir report\output_razorpay --no-llm
```

The adapter fetches captured test-mode payments and maps payment fields into the canonical gateway and ERP rows. Razorpay does not provide the merchant bank statement through this API, so the adapter generates clearly labeled simulated bank rows from settlement net amounts and plants one mismatch for verifier demonstration. A production deployment should replace that simulated bank feed with a real bank statement adapter.

### Dashboard

```powershell
streamlit run dashboard\app.py
```

Keep API keys in `.env`; never commit that file or paste its contents into a demo or issue.
