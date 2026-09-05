# RazorRecon Finance Control Tower

### Run the books. Protect the cash position.

RazorRecon is an adversarial finance-operations controller built for the Razorpay AI Buildathon. It reconciles bank credits, payment-gateway settlements, and ERP entries across a full transaction batch.

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

---

## Architecture Overview

### System Flow Diagram (Mermaid)

```mermaid
graph TD
    A["Bank Statement CSV<br/>(date, credit, ref_number)"] --> L["Source Adapter Layer<br/>(Normalize to canonical schema)"]
    B["Razorpay Gateway API<br/>(txn_ref, net_amount, date)"] --> L
    C["ERP Ledger<br/>(txn_ref, amount, entry_date)"] --> L
    
    L --> M["MATCHER STAGE"]
    
    M --> M1["PASS 1: Deterministic<br/>(88% of batch)"]
    M1 --> M1A["• Exact ref_number lookup<br/>• Amount within tolerance<br/>• Timing within window"]
    M1A --> M1B["✓ Single Clear Match?<br/>YES → DETERMINISTIC proposal<br/>conf = 1.0"]
    
    M1 --> M1C["✗ Ambiguous Case?<br/>Zero/Multiple refs<br/>OOT amount/timing"]
    
    M1C --> M2["PASS 2: LLM-Assisted<br/>(12% of batch)"]
    M2 --> M2A["• Groq/Claude reasoning<br/>• Split settlement detection<br/>• Fee/tax variance explanation"]
    M2A --> M2B["→ Low-confidence proposal<br/>conf = 0.2-0.8<br/>Fallback: Heuristic stub"]
    
    M1B --> V["VERIFIER STAGE<br/>(Adversarial Multi-Check)"]
    M2B --> V
    
    V --> V1["CHECK 1: Identity<br/>(Ref Uniqueness)"]
    V1 --> V1R{{"Ref used<br/>multiple times<br/>(unaccounted)?"}}
    V1R -->|YES| VR1["⚠️ REVIEW<br/>conf=0.3<br/>(Potential dup/split)"]
    V1R -->|NO| V2["CHECK 2: Amount<br/>(Sum vs net_amount)"]
    
    V2 --> V2R{{"Diff within<br/>tolerance?"}}
    V2R -->|✓ diff ≤ tolerance| V3["CHECK 3: Timing<br/>(Settlement window)"]
    V2R -->|~ diff in review zone| V2B["→ Gray-Zone<br/>(May escalate to LLM)"]
    V2R -->|✗ diff > exception| VEX1["❌ EXCEPTION<br/>conf=0.95<br/>(Amount mismatch)"]
    
    V3 --> V3R{{"Days between<br/>within policy?"}}
    V3R -->|✓ YES| V4["CHECK 4: Split<br/>(Multi-row rules)"]
    V3R -->|✗ NO| VR2["⚠️ REVIEW<br/>conf=0.3<br/>(Suspicious timing)"]
    
    V4 --> V4R{{"Valid split<br/>config?"}}
    V4R -->|✓ YES| VFINAL1["✅ RECONCILED<br/>conf=0.97<br/>(Auto-approve)"]
    V4R -->|✗ NO| VEX2["❌ EXCEPTION<br/>(Too many splits)"]
    
    V2B --> LLM["LLM Gray-Zone Judgment<br/>(Only if configured)"]
    LLM --> LLMOUT{{"LLM Verdict?"}}
    LLMOUT -->|Confident| VFINAL2["✅ RECONCILED"]
    LLMOUT -->|Uncertain| VR3["⚠️ REVIEW"]
    LLMOUT -->|Reject| VEX3["❌ EXCEPTION"]
    
    VR1 --> QUEUE["Result Queues"]
    VR2 --> QUEUE
    VR3 --> QUEUE
    VFINAL1 --> QUEUE
    VFINAL2 --> QUEUE
    VEX1 --> QUEUE
    VEX2 --> QUEUE
    VEX3 --> QUEUE
    
    QUEUE --> Q1["reconciled.csv<br/>(440 txns)<br/>✓ Auto-approve"]
    QUEUE --> Q2["review_queue.csv<br/>(49 txns)<br/>⚠️ Human review"]
    QUEUE --> Q3["exceptions.csv<br/>(11 txns)<br/>❌ Reject"]
    
    Q1 --> D["Streamlit Dashboard"]
    Q2 --> D
    Q3 --> D
    
    D --> D1["Batch KPIs<br/>(agreement %, verdicts)"]
    D --> D2["Per-txn drill-down<br/>(checks, reasoning, confidence)"]
    D --> D3["Human Actions<br/>(approve/reject/investigate)<br/>with audit log"]
    
    style A fill:#e1f5ff
    style B fill:#e1f5ff
    style C fill:#e1f5ff
    style VFINAL1 fill:#c8e6c9
    style VFINAL2 fill:#c8e6c9
    style VR1 fill:#fff9c4
    style VR2 fill:#fff9c4
    style VR3 fill:#fff9c4
    style VEX1 fill:#ffcdd2
    style VEX2 fill:#ffcdd2
    style VEX3 fill:#ffcdd2
    style LLM fill:#f3e5f5
    style M1B fill:#c8e6c9
    style M2B fill:#fff3e0
```

---

### Detailed Decision Flowchart

```mermaid
graph TD
    TX["Transaction Received<br/>(ERP ↔ Gateway)"]
    
    TX --> M1["Matcher Pass 1<br/>Deterministic Check"]
    M1 --> REF{{"Exact ref_number<br/>in bank<br/>statement?"}}
    
    REF -->|❌ Zero matches| M2["Matcher Pass 2<br/>LLM-Assisted"]
    REF -->|✓ One match| AMT["Amount Check<br/>(confidence=1.0)"]
    REF -->|⚠️ Multiple| M2
    
    AMT --> AMTC{{"Credit within<br/>tolerance?"}}
    AMTC -->|✓ YES| TIME["Timing Check"]
    AMTC -->|✗ OOT| M2
    
    TIME --> TIMEC{{"Days ≤<br/>max window?"}}
    TIMEC -->|✓ YES| DET["✅ Deterministic<br/>Proposal<br/>conf=1.0"]
    TIMEC -->|✗ OOT| M2
    
    M2 --> LLM_M["LLM Match<br/>(zero/multi/OOT)"]
    LLM_M --> PROP["🔍 Proposal<br/>(conf=0.2-0.8)"]
    DET --> VERIF["VERIFIER<br/>(Trust but Verify)"]
    PROP --> VERIF
    
    VERIF --> VID["Identity Check"]
    VID --> VIDC{{"Ref unused<br/>elsewhere?"}}
    VIDC -->|❌ Dup/split<br/>unclaimed| VR["→ REVIEW<br/>(low conf)"]
    VIDC -->|✓ Clean| VAMT["Amount Check"]
    
    VAMT --> VAMTC{{"Sum within<br/>basic tolerance?"}}
    VAMTC -->|✓ YES| VTIME["Timing Check"]
    VAMTC -->|~ Gray-Zone| GZONE["Gray-Zone<br/>Decision<br/>(flags for LLM)"]
    VAMTC -->|✗ NO| EXC["→ EXCEPTION<br/>(rejected)"]
    
    VTIME --> VTIMEC{{"Arrival<br/>within policy?"}}
    VTIMEC -->|✓ YES| VSPLIT["Split Check"]
    VTIMEC -->|✗ NO| VR
    
    VSPLIT --> VSPLITC{{"Multi-row valid?"}}
    VSPLITC -->|✓ YES| RECON["✅ RECONCILED<br/>(auto-approve)<br/>conf=0.97"]
    VSPLITC -->|✗ NO| EXC
    
    GZONE --> LLMV["LLM Gray-Zone<br/>Judgment"]
    LLMV --> LLMVD{{"LLM says?"}}
    LLMVD -->|Confident| RECON
    LLMVD -->|Unsure| VR
    LLMVD -->|Reject| EXC
    
    RECON --> OUT["📊 Output"]
    VR --> OUT
    EXC --> OUT
    
    OUT --> CSV1["reconciled.csv<br/>✓ 440"]
    OUT --> CSV2["review_queue.csv<br/>⚠️ 49"]
    OUT --> CSV3["exceptions.csv<br/>❌ 11"]
    
    CSV1 --> AUDIT["audit_trail.json<br/>(full reasoning)"]
    CSV2 --> AUDIT
    CSV3 --> AUDIT
    
    AUDIT --> DASH["Dashboard<br/>(Human interface)"]
    DASH --> HUM["Human Reviews<br/>Queue + Makes Decisions<br/>(logged audit trail)"]
    
    style TX fill:#e3f2fd
    style DET fill:#c8e6c9
    style RECON fill:#a5d6a7
    style VR fill:#fff9c4
    style EXC fill:#ffcdd2
    style GZONE fill:#f3e5f5
    style LLMV fill:#f3e5f5
    style HUM fill:#e0f2f1
    style DASH fill:#fce4ec
```

---

### Component State Machine

```mermaid
stateDiagram-v2
    [*] --> Received: Transaction<br/>Enters Pipeline
    
    Received --> Pass1: Matcher<br/>Phase Start
    
    Pass1 --> Deterministic: Single ref +<br/>Within tolerance
    Pass1 --> Ambiguous: Zero/Multi refs<br/>OR OOT amounts/timing
    
    Ambiguous --> Pass2: Matcher<br/>Phase 2
    Pass2 --> Proposed: LLM Proposal<br/>(low conf)
    
    Deterministic --> Proposed: High confidence<br/>Proposal ready
    
    Proposed --> VerifierStart: Verifier<br/>Phase Start
    
    VerifierStart --> CheckIdentity: Identity<br/>Check
    CheckIdentity --> IdentityFail: Duplicate/<br/>Unclaimed<br/>Ref
    IdentityFail --> ReviewQueue1: Flag for<br/>Review
    
    CheckIdentity --> CheckAmount: Amount<br/>Check
    CheckAmount --> AmountPass: Within<br/>Basic<br/>Tolerance
    CheckAmount --> AmountGray: Gray-Zone<br/>Variance
    CheckAmount --> AmountFail: Large<br/>Mismatch
    
    AmountPass --> CheckTiming: Timing<br/>Check
    AmountGray --> LLMGray: Escalate<br/>to LLM
    AmountFail --> ExceptionQueue1: Flag<br/>Exception
    
    CheckTiming --> TimingPass: Within<br/>Window
    CheckTiming --> TimingFail: Suspicious<br/>Delay
    TimingFail --> ReviewQueue2: Flag for<br/>Review
    
    TimingPass --> CheckSplit: Split<br/>Validation
    CheckSplit --> SplitValid: Multi-row<br/>OK
    CheckSplit --> SplitFail: Too many<br/>Rows/Invalid
    SplitFail --> ExceptionQueue2: Flag<br/>Exception
    
    SplitValid --> Reconciled: Auto-Approve<br/>(conf=0.97)
    
    LLMGray --> LLMDecision: LLM Gray-Zone<br/>Judgment
    LLMDecision --> Reconciled: LLM: Accept
    LLMDecision --> ReviewQueue3: LLM: Unsure
    LLMDecision --> ExceptionQueue3: LLM: Reject
    
    Reconciled --> ReconciledCSV: Write to<br/>reconciled.csv
    ReviewQueue1 --> ReviewCSV: Write to<br/>review_queue.csv
    ReviewQueue2 --> ReviewCSV
    ReviewQueue3 --> ReviewCSV
    ExceptionQueue1 --> ExceptionCSV: Write to<br/>exceptions.csv
    ExceptionQueue2 --> ExceptionCSV
    ExceptionQueue3 --> ExceptionCSV
    
    ReconciledCSV --> Dashboard: Render<br/>in Dashboard
    ReviewCSV --> Dashboard
    ExceptionCSV --> Dashboard
    
    Dashboard --> HumanReview: Human Operator<br/>Makes Decision
    HumanReview --> [*]: Transaction<br/>Settled
    
    style Reconciled fill:#90EE90
    style ReviewQueue1 fill:#FFFF99
    style ReviewQueue2 fill:#FFFF99
    style ReviewQueue3 fill:#FFFF99
    style ExceptionQueue1 fill:#FF6B6B
    style ExceptionQueue2 fill:#FF6B6B
    style ExceptionQueue3 fill:#FF6B6B
    style LLMGray fill:#E6D7FF
    style LLMDecision fill:#E6D7FF
    style Dashboard fill:#FFE4E1
    style HumanReview fill:#90EE90
```

---

### Data Transformation Pipeline

```mermaid
sequenceDiagram
    participant Input as Bank/Gateway/ERP CSV
    participant Adapter as Source Adapter
    participant Matcher as Matcher (2-Pass)
    participant Verifier as Verifier (Multi-Check)
    participant Output as Result Queues
    participant Dashboard as Streamlit Dashboard
    
    Input->>Adapter: Raw CSVs loaded
    Adapter->>Adapter: Normalize schema<br/>(canonical ref, amount, date)
    Adapter->>Matcher: Unified txn_ref, net_amount, entry_date
    
    Matcher->>Matcher: Pass 1: Deterministic<br/>(88% of batch)
    Matcher->>Matcher: Pass 2: LLM-Assisted<br/>(12% of batch)
    Matcher->>Verifier: Proposals with confidence
    
    Verifier->>Verifier: Check 1: Identity<br/>(ref uniqueness)
    Verifier->>Verifier: Check 2: Amount<br/>(tolerance tiers)
    Verifier->>Verifier: Check 3: Timing<br/>(arrival window)
    Verifier->>Verifier: Check 4: Split<br/>(multi-row rules)
    
    alt All Deterministic Checks Pass
        Verifier->>Output: ✅ RECONCILED<br/>(conf=0.97)
    else Gray-Zone (Amount/Confidence Ambiguous)
        Verifier->>Verifier: LLM Gray-Zone Judgment
        Verifier->>Output: Verdict (RECON/REVIEW/EXCEPTION)
    else Hard Policy Violation
        Verifier->>Output: ⚠️ REVIEW or ❌ EXCEPTION
    end
    
    Output->>Output: Split into 3 queues<br/>reconciled.csv (440)<br/>review_queue.csv (49)<br/>exceptions.csv (11)
    Output->>Dashboard: Load results + audit_trail.json
    
    Dashboard->>Dashboard: Render KPIs<br/>Batch agreement %, verdict distribution<br/>Per-txn drill-down
    
    Dashboard->>Dashboard: User Actions<br/>Approve / Reject / Investigate
    
    Dashboard->>Dashboard: Log decisions to audit trail<br/>(permanent record)
    
    Dashboard->>Dashboard: Generate reconciliation summary
```

---

### Policy Tolerance Matrix

```mermaid
graph LR
    A["Amount Variance<br/>Rupees"] --> B["0 to 50"]
    B --> B1["✅ PASS<br/>Basic tolerance"]
    
    A --> C["50 to 150"]
    C --> C1["✅ PASS<br/>Fee/tax/refund"]
    
    A --> D["150 to 500"]
    D --> D1["⚠️ REVIEW<br/>Gray-zone"]
    
    A --> E["500+"]
    E --> E1["❌ EXCEPTION<br/>Large variance"]
    
    F["Timing Variance<br/>Days"] --> G["0 to 1"]
    G --> G1["✅ PASS<br/>Same/next day"]
    
    F --> H["1 to 5"]
    H --> H1["✅ PASS<br/>Normal window"]
    
    F --> I["5+"]
    I --> I1["⚠️ REVIEW<br/>Suspicious delay"]
    
    J["Split Settlement<br/>Config"] --> K["Single row<br/>within tol"]
    K --> K1["✅ PASS<br/>Standard"]
    
    J --> L["Multi-row sum<br/>within tol"]
    L --> L1["✅ PASS<br/>Valid split"]
    
    J --> M["Multi-row<br/>exceeds max"]
    M --> M1["❌ EXCEPTION<br/>Policy violation"]
    
    style B1 fill:#c8e6c9
    style C1 fill:#c8e6c9
    style D1 fill:#fff9c4
    style E1 fill:#ffcdd2
    style G1 fill:#c8e6c9
    style H1 fill:#c8e6c9
    style I1 fill:#fff9c4
    style K1 fill:#c8e6c9
    style L1 fill:#c8e6c9
    style M1 fill:#ffcdd2
```

---

### System-Level ASCII Reference

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    DATA INGESTION & NORMALIZATION LAYER                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Bank Statement CSV          Gateway Settlement API         ERP Ledger   │
│  ├─ date                     ├─ txn_ref (PG txn ID)        ├─ entry_date  │
│  ├─ credit                   ├─ net_amount (after fees)    ├─ txn_ref     │
│  ├─ ref_number               ├─ gateway_settlement_date    ├─ amount      │
│  └─ bank_id (unique)         └─ status (captured/settled)  └─ category    │
│                                                                           │
│                    Source Adapters (CSV / Razorpay API)                 │
│          Normalize → canonical schema → unified txn_ref key              │
│                                                                           │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     MATCHER STAGE (Two-Pass Strategy)                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  PASS 1: Deterministic (88%)  │  PASS 2: LLM-Assisted (12%)            │
│  ─────────────────────────────┼────────────────────────────────────     │
│  • Exact ref match            │  • Zero bank rows for ref             │
│  • Amount within tolerance    │  • Multiple bank rows (dup/split)     │
│  • Timing within window       │  • Amount outside tolerance           │
│  • Result: conf=1.0           │  • Timing outside window              │
│                               │  • Result: conf=0.2-0.8 (Groq/stub)   │
│                                                                           │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ Proposals
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│           VERIFIER STAGE (Adversarial Multi-Check Authority)            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  DETERMINISTIC CHECKS (Authoritative):                                  │
│  1. Identity Check    → Ref reused elsewhere unclaimed?                 │
│  2. Amount Check      → Tiers: PASS | GRAY-ZONE | EXCEPTION            │
│  3. Timing Check      → Settlement within policy window?                │
│  4. Split Check       → Multi-row rules & max_split_parts valid?        │
│                                                                           │
│  ESCALATION:                                                             │
│  • All checks pass      → RECONCILED (conf=0.97, auto-approve)          │
│  • Gray-zone amount     → LLM gray-zone judgment (if configured)        │
│  • Hard policy break    → EXCEPTION or REVIEW                           │
│                                                                           │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
    RECONCILED           REVIEW                EXCEPTION
    (440 txns)          (49 txns)              (11 txns)
         │                 │                       │
         └───────���─────────┼───────────────────────┘
                           ▼
                    ┌──────────────────┐
                    │  Audit Trail     │
                    │  + Dashboard     │
                    │  + Human Loop    │
                    └──────────────────┘
```

---

## What the Dashboard Shows

- Batch-level reconciliation and safety KPIs
- Deterministic versus LLM-assisted resolution breakdown
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

The adapter fetches captured test-mode payments and maps payment fields into the canonical gateway and ERP rows. Razorpay does not provide the merchant bank statement through this API, so the adapter simulates the bank side from the payment's settlement details.

Razorpay test-mode payments are fetched through the live adapter. Because Razorpay does not expose the merchant bank statement through the Payments API, the demo explicitly simulates the bank side from the payment settlement metadata (amount, date, reference ID).

## Dashboard

```powershell
streamlit run dashboard\app.py
```

Keep API keys in `.env`; never commit that file or paste its contents into a demo or issue.
