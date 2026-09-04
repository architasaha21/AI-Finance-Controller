import os
import json
import time
from datetime import datetime

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# ============================================================================
# CONFIG
# ============================================================================
st.set_page_config(
    page_title="AI Finance Controller — Reconciliation Dashboard",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# STYLING — modern futuristic glassmorphism dark theme
# ============================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"] { font-family: 'Outfit', sans-serif; }

/* ── Metric cards with glow hover ── */
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    padding: 16px 22px;
    border-radius: 14px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    backdrop-filter: blur(10px);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
div[data-testid="metric-container"]:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 24px rgba(255, 75, 75, 0.12), 0 4px 12px rgba(0,0,0,0.2);
    border-color: rgba(255, 75, 75, 0.25);
}

/* ── Main title gradient ── */
.main-title {
    font-weight: 800;
    font-size: 2.5rem;
    background: linear-gradient(135deg, #FF4B4B 0%, #FF8F8F 50%, #FFB8B8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0;
    letter-spacing: -0.5px;
}
.subtitle {
    color: rgba(255,255,255,0.45);
    font-size: 0.95rem;
    margin-bottom: 24px;
    margin-top: 4px;
    font-weight: 300;
    letter-spacing: 0.2px;
}

/* ── Section headers with accent bar ── */
.section-header {
    font-weight: 600;
    font-size: 1.3rem;
    margin-top: 8px;
    margin-bottom: 16px;
    border-left: 4px solid #FF4B4B;
    padding-left: 12px;
    letter-spacing: -0.2px;
}

/* ── Verdict badges ── */
.badge {
    padding: 4px 12px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 0.82rem;
    display: inline-block;
    letter-spacing: 0.3px;
}
.badge-reconciled {
    background: linear-gradient(135deg, rgba(46,204,113,0.18), rgba(46,204,113,0.08));
    color: #2ecc71; border: 1px solid rgba(46,204,113,0.3);
}
.badge-review {
    background: linear-gradient(135deg, rgba(241,196,15,0.18), rgba(241,196,15,0.08));
    color: #f1c40f; border: 1px solid rgba(241,196,15,0.3);
}
.badge-exception {
    background: linear-gradient(135deg, rgba(231,76,60,0.18), rgba(231,76,60,0.08));
    color: #e74c3c; border: 1px solid rgba(231,76,60,0.3);
}
.badge-decision {
    background: linear-gradient(135deg, rgba(52,152,219,0.18), rgba(52,152,219,0.08));
    color: #3498db; border: 1px solid rgba(52,152,219,0.3);
}

/* ── Detail cards (glassmorphism) ── */
.detail-card {
    background: linear-gradient(145deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.005) 100%);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    padding: 22px;
    margin-bottom: 16px;
    backdrop-filter: blur(8px);
    box-shadow: 0 4px 16px rgba(0,0,0,0.15);
}
.detail-title {
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 16px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding-bottom: 10px;
}

/* ── Summary stat pills ── */
.stat-pill {
    display: inline-block;
    padding: 5px 14px;
    border-radius: 20px;
    margin-right: 6px;
    margin-bottom: 6px;
    font-size: 0.85rem;
    font-weight: 500;
    letter-spacing: 0.2px;
    backdrop-filter: blur(4px);
}

/* ── Tab styling ── */
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
    font-size: 0.95rem;
    font-weight: 600;
    padding: 10px 20px;
    border-radius: 12px 12px 0 0;
    letter-spacing: 0.1px;
}

/* ── Safety card glow ── */
.safety-card {
    border-radius: 14px;
    padding: 14px 22px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    backdrop-filter: blur(8px);
}
.safety-card-ok {
    background: linear-gradient(135deg, rgba(46,204,113,0.15), rgba(46,204,113,0.05));
    border: 2px solid rgba(46,204,113,0.4);
}
.safety-card-danger {
    background: linear-gradient(135deg, rgba(231,76,60,0.15), rgba(231,76,60,0.05));
    border: 2px solid rgba(231,76,60,0.4);
}

/* ── Button styling ── */
.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 0.2px !important;
    transition: all 0.2s ease !important;
}
.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2) !important;
}
</style>
""", unsafe_allow_html=True)


# ============================================================================
# HUMAN DECISION PERSISTENCE
# ============================================================================
def _decisions_path(report_dir):
    return os.path.join(report_dir, "human_decisions.json")


def load_decisions(report_dir="report/output"):
    path = _decisions_path(report_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            records = json.load(f)
    except Exception:
        return {}
    return {r["txn_ref"]: r for r in records}


def save_decision(txn_ref, decision, report_dir="report/output"):
    path = _decisions_path(report_dir)
    records = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            records = []
    records.append({
        "txn_ref": txn_ref,
        "decision": decision,
        "timestamp": datetime.now().isoformat(),
        "decided_by": "demo_user",
    })
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


# ============================================================================
# DATA LOADING
# ============================================================================
@st.cache_data
def load_all_data(report_dir="report/output"):
    paths = {
        "reconciled": os.path.join(report_dir, "reconciled.csv"),
        "review": os.path.join(report_dir, "review_queue.csv"),
        "exceptions": os.path.join(report_dir, "exceptions.csv"),
        "audit": os.path.join(report_dir, "audit_trail.json"),
        "metrics": os.path.join(report_dir, "metrics_summary.json"),
        "policy": "agents/policy.json",
    }

    if not all(os.path.exists(paths[k]) for k in ("reconciled", "review", "exceptions")):
        return None

    try:
        df_reco = pd.read_csv(paths["reconciled"])
        df_rev = pd.read_csv(paths["review"])
        df_ex = pd.read_csv(paths["exceptions"])
    except Exception as e:
        st.error(f"Error loading CSV files: {e}")
        return None

    audit_trail = []
    if os.path.exists(paths["audit"]):
        try:
            with open(paths["audit"], "r", encoding="utf-8") as f:
                audit_trail = json.load(f)
        except Exception:
            pass

    metrics_summary = None
    if os.path.exists(paths["metrics"]):
        try:
            with open(paths["metrics"], "r", encoding="utf-8") as f:
                metrics_summary = json.load(f)
        except Exception:
            pass

    policy = None
    if os.path.exists(paths["policy"]):
        try:
            with open(paths["policy"], "r", encoding="utf-8") as f:
                policy = json.load(f)
        except Exception:
            pass

    return {
        "reconciled": df_reco, "review": df_rev, "exceptions": df_ex,
        "audit_trail": audit_trail, "metrics_summary": metrics_summary,
        "policy": policy,
    }


# ============================================================================
# CHART HELPERS
# ============================================================================
def verdict_donut(n_reco, n_rev, n_ex):
    fig = go.Figure(data=[go.Pie(
        labels=["Reconciled", "Review", "Exception"],
        values=[n_reco, n_rev, n_ex],
        hole=0.62,
        marker_colors=["#2ecc71", "#f1c40f", "#e74c3c"],
        textinfo="label+percent",
        textfont=dict(size=13, color="white"),
        hoverinfo="label+value+percent",
    )])
    fig.update_layout(
        showlegend=True, height=320,
        legend=dict(orientation="h", yanchor="bottom", y=-0.12,
                    xanchor="center", x=0.5, font=dict(color="white", size=12)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="white", margin=dict(t=10, b=40, l=10, r=10),
    )
    return fig


def confidence_gauge(value, label):
    color = "#2ecc71" if value >= 0.85 else "#f1c40f" if value >= 0.5 else "#e74c3c"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(value * 100, 1),
        number={"suffix": "%", "font": {"size": 26, "color": "white"}},
        title={"text": label, "font": {"size": 13, "color": "#aaa"}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#555", "tickwidth": 1},
            "bar": {"color": color, "thickness": 0.7},
            "bgcolor": "rgba(255,255,255,0.03)",
            "borderwidth": 1, "bordercolor": "rgba(255,255,255,0.1)",
            "steps": [
                {"range": [0, 50], "color": "rgba(231,76,60,0.06)"},
                {"range": [50, 85], "color": "rgba(241,196,15,0.06)"},
                {"range": [85, 100], "color": "rgba(46,204,113,0.06)"},
            ],
        },
    ))
    fig.update_layout(
        height=180, margin=dict(t=35, b=10, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)", font_color="white",
    )
    return fig


def verdict_badge_html(verdict):
    cls = {"RECONCILED": "badge-reconciled", "REVIEW": "badge-review",
           "EXCEPTION": "badge-exception"}.get(verdict, "badge-review")
    icon = {"RECONCILED": "🟢", "REVIEW": "🟡", "EXCEPTION": "🔴"}.get(verdict, "⚪")
    return f"<span class='badge {cls}'>{icon} {verdict}</span>"


# ============================================================================
# MAIN
# ============================================================================
def main():
    st.markdown(
        '<div class="main-title">💼 AI Finance Controller</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="subtitle">'
        'One agent proposes a reconciliation. A second, independent agent '
        'tries to prove it wrong before it counts.'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Sidebar ──────────────────────────────────────────────────────
    st.sidebar.markdown("### 🗂️ Data Source")
    data_source = st.sidebar.radio(
        "Batch", ["Synthetic batch (500 txns)", "Razorpay test mode (live)"],
        index=0, label_visibility="collapsed",
    )
    report_dir = (
        "report/output" if "Synthetic" in data_source
        else "report/output_razorpay"
    )

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    # ── Load data ────────────────────────────────────────────────────
    data = load_all_data(report_dir)
    if data is None:
        if "Razorpay" in data_source:
            st.warning(
                "⚠️ No Razorpay output found. Run the pipeline with "
                "`--source razorpay` first, or switch to Synthetic batch."
            )
        else:
            st.error("⚠️ No reconciliation output found. Run the pipeline first.")
            st.info(
                "`python agents/pipeline.py --data ../data/output "
                "--policy policy.json --outdir ../report/output`"
            )
        return

    df_reco = data["reconciled"]
    df_rev = data["review"]
    df_ex = data["exceptions"]
    audit_trail = data["audit_trail"]
    metrics_summary = data["metrics_summary"]
    policy = data["policy"]

    df_all = pd.concat([df_reco, df_rev, df_ex], ignore_index=True)
    total_txns = len(df_all)
    decisions = load_decisions(report_dir)

    # ── Sidebar: Human Review Summary ────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📋 Human Review Log")
    n_approved = sum(1 for d in decisions.values() if d["decision"] == "APPROVED")
    n_rejected = sum(1 for d in decisions.values() if d["decision"] == "REJECTED")
    n_investigating = sum(1 for d in decisions.values() if d["decision"] == "INVESTIGATING")
    n_queue_total = len(df_rev) + len(df_ex)
    n_pending = max(n_queue_total - len(decisions), 0)

    st.sidebar.metric("Pending review", n_pending)
    st.sidebar.markdown(
        f"✅ {n_approved} approved &nbsp;&nbsp; "
        f"❌ {n_rejected} rejected &nbsp;&nbsp; "
        f"🔎 {n_investigating} investigating",
        unsafe_allow_html=True,
    )

    # ── Sidebar: Policy Quick Ref ────────────────────────────────────
    if policy is not None:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### ⚙️ Policy Quick Ref")
        for key, val in policy.items():
            if key == "_comments":
                continue
            readable = key.replace("_", " ").title()
            if isinstance(val, bool):
                dv = "✅ Yes" if val else "❌ No"
            elif "rupees" in key:
                dv = f"₹{val:,.2f}"
            elif "days" in key:
                dv = f"{val} day(s)"
            elif "confidence" in key:
                dv = f"{val:.0%}"
            else:
                dv = str(val)
            st.sidebar.markdown(f"**{readable}:** {dv}")

    # ── Tabs ─────────────────────────────────────────────────────────
    tab_overview, tab_queue, tab_audit, tab_policy = st.tabs(
        ["📊 Overview", "⚠️ Review Queue", "🔍 Audit Trail", "📋 Policy"]
    )

    # =================================================================
    # TAB: OVERVIEW
    # =================================================================
    with tab_overview:
        st.markdown(
            '<div class="section-header">Batch Summary</div>',
            unsafe_allow_html=True,
        )

        # ── KPI row ──────────────────────────────────────────────────
        col1, col2, col3, col4, col5 = st.columns(5)
        pct_reco = (len(df_reco) / total_txns * 100) if total_txns else 0
        pct_rev = (len(df_rev) / total_txns * 100) if total_txns else 0
        pct_ex = (len(df_ex) / total_txns * 100) if total_txns else 0
        det_count = int((df_all["matcher_method"] == "deterministic").sum())
        pct_det = (det_count / total_txns * 100) if total_txns else 0

        with col1:
            st.metric("Total Transactions", f"{total_txns}")
        with col2:
            st.metric("🟢 Reconciled", f"{pct_reco:.1f}%",
                       delta=f"{len(df_reco)} rows")
        with col3:
            st.metric("🟡 Review", f"{pct_rev:.1f}%",
                       delta=f"{len(df_rev)} rows")
        with col4:
            st.metric("🔴 Exception", f"{pct_ex:.1f}%",
                       delta=f"{len(df_ex)} rows")
        with col5:
            st.metric("🤖 Resolved by Rules", f"{pct_det:.0f}%",
                       help="Deterministic policy checks vs LLM reasoning",
                       delta=f"{100 - pct_det:.0f}% via LLM")

        # ── Accuracy stats ───────────────────────────────────────────
        if metrics_summary is not None:
            st.markdown("<br>", unsafe_allow_html=True)
            col_a1, col_a2, col_a3 = st.columns([1, 1, 2])
            match_rate = metrics_summary.get("match_rate", 0) * 100
            dangerous_fp = metrics_summary.get("dangerous_false_positives", 0)

            with col_a1:
                st.metric("🎯 Ground Truth Match Rate", f"{match_rate:.1f}%")

            with col_a2:
                is_safe = dangerous_fp == 0
                card_cls = "safety-card-ok" if is_safe else "safety-card-danger"
                color = "#2ecc71" if is_safe else "#e74c3c"
                icon = "🛡️" if is_safe else "⚠️"
                st.markdown(f"""
                    <div class="safety-card {card_cls}">
                        <span style="font-size:0.82rem;color:{color};font-weight:600;
                                     text-transform:uppercase;">{icon} Dangerous False Positives</span>
                        <div style="font-size:2.2rem;font-weight:700;color:{color};
                                    margin-top:5px;">{dangerous_fp}</div>
                    </div>
                """, unsafe_allow_html=True)

            with col_a3:
                st.markdown("""
                    <div style="font-size:0.85rem;color:rgba(255,255,255,0.4);
                                padding-top:5px;line-height:1.5;">
                        <strong style="color:rgba(255,255,255,0.6);">
                            ℹ️ Why this number matters most</strong><br/>
                        A dangerous false positive means the system marked something
                        <b>RECONCILED</b> that should have been flagged. A wrong REVIEW
                        costs a few minutes — a wrong RECONCILED hides a real problem.
                        <b>Zero is the target.</b>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.caption(
                "ℹ️ Run `metrics.py` to see accuracy stats vs ground truth."
            )

        # ── Chart + Live replay side-by-side ─────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        col_chart, col_replay = st.columns([1, 1])

        with col_chart:
            st.markdown("##### Verdict Breakdown")
            st.plotly_chart(
                verdict_donut(len(df_reco), len(df_rev), len(df_ex)),
                use_container_width=True,
            )

        with col_replay:
            st.markdown("##### ▶ Live Reconciliation Replay")
            st.caption(
                "Watch the AI matcher and adversarial verifier process "
                "transactions in real time — including the hero case where "
                "the verifier catches what the matcher missed."
            )
            if st.button("▶ Run Replay", use_container_width=True):
                feed = st.empty()
                lines = []
                # Hand-picked refs: hero case TXN100109 buried mid-stream
                hero_refs = [
                    "TXN100000", "TXN100001", "TXN100006",
                    "TXN100024", "TXN100038", "TXN100109",
                    "TXN100110", "TXN100143", "TXN100200",
                    "TXN100299",
                ]
                ref_lookup = {r["txn_ref"]: r for r in audit_trail}
                sample = [ref_lookup[r] for r in hero_refs if r in ref_lookup]
                if not sample:
                    sample = audit_trail[:10]

                for rec in sample:
                    verdict = rec["verifier"]["verdict"]
                    icon = {"RECONCILED": "🟢", "REVIEW": "🟡",
                            "EXCEPTION": "🔴"}.get(verdict, "⚪")
                    lines.append(
                        f"{icon} {rec['txn_ref']}  →  "
                        f"matcher: {rec['matcher']['method']} "
                        f"({rec['matcher']['confidence']:.2f})  →  "
                        f"verifier: {verdict}"
                    )
                    feed.code("\n".join(lines), language=None)
                    time.sleep(0.45)
                st.success(
                    "✅ Replay complete — see Review Queue and "
                    "Audit Trail tabs for full detail."
                )

    # =================================================================
    # TAB: REVIEW QUEUE
    # =================================================================
    with tab_queue:
        st.markdown(
            '<div class="section-header">Exception &amp; Review Queue</div>',
            unsafe_allow_html=True,
        )

        df_queue = pd.concat([df_rev, df_ex], ignore_index=True)

        if len(df_queue) == 0:
            st.success(
                "🎉 Review and Exception queues are both empty — "
                "all transactions resolved clean."
            )
        else:
            # ── Decision summary pills ───────────────────────────────
            queue_refs = set(df_queue["txn_ref"].tolist())
            decided_refs = {
                ref: d for ref, d in decisions.items() if ref in queue_refs
            }
            q_approved = sum(
                1 for d in decided_refs.values()
                if d["decision"] == "APPROVED"
            )
            q_rejected = sum(
                1 for d in decided_refs.values()
                if d["decision"] == "REJECTED"
            )
            q_investigating = sum(
                1 for d in decided_refs.values()
                if d["decision"] == "INVESTIGATING"
            )
            q_pending = len(queue_refs) - len(decided_refs)

            st.markdown(
                f'<span class="stat-pill" style="background:rgba(241,196,15,0.12);color:#f1c40f;">'
                f'⏳ {q_pending} pending</span>'
                f'<span class="stat-pill" style="background:rgba(46,204,113,0.12);color:#2ecc71;">'
                f'✅ {q_approved} approved</span>'
                f'<span class="stat-pill" style="background:rgba(231,76,60,0.12);color:#e74c3c;">'
                f'❌ {q_rejected} rejected</span>'
                f'<span class="stat-pill" style="background:rgba(52,152,219,0.12);color:#3498db;">'
                f'🔎 {q_investigating} investigating</span>',
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)

            # ── Filter ───────────────────────────────────────────────
            queue_filter = st.selectbox(
                "Filter:",
                ["Both REVIEW & EXCEPTION", "REVIEW Only", "EXCEPTION Only"],
                index=0,
            )

            filtered_df = df_queue.copy()
            if queue_filter == "REVIEW Only":
                filtered_df = df_queue[
                    df_queue["verifier_verdict"] == "REVIEW"
                ].copy()
            elif queue_filter == "EXCEPTION Only":
                filtered_df = df_queue[
                    df_queue["verifier_verdict"] == "EXCEPTION"
                ].copy()

            # Add decision column, sort pending-first
            filtered_df = filtered_df.copy()
            filtered_df["human_decision"] = filtered_df["txn_ref"].map(
                lambda ref: decisions.get(ref, {}).get("decision", "—")
            )
            sort_order = {"—": 0, "INVESTIGATING": 1, "APPROVED": 2, "REJECTED": 3}
            filtered_df["_sort"] = (
                filtered_df["human_decision"].map(sort_order).fillna(4)
            )
            sorted_df = filtered_df.sort_values(
                by=["_sort", "verifier_verdict", "verifier_confidence"],
                ascending=[True, True, True],
            )

            display_df = sorted_df[[
                "txn_ref", "verifier_verdict", "reason",
                "matcher_confidence", "verifier_confidence",
                "escalated_to_llm", "human_decision",
            ]].rename(columns={
                "txn_ref": "Transaction Ref",
                "verifier_verdict": "Verdict",
                "reason": "Flag Reason",
                "matcher_confidence": "Matcher Conf",
                "verifier_confidence": "Verifier Conf",
                "escalated_to_llm": "LLM Escalated",
                "human_decision": "Your Decision",
            })

            st.dataframe(
                display_df, use_container_width=True, hide_index=True,
                column_config={
                    "Matcher Conf": st.column_config.NumberColumn(format="%.2f"),
                    "Verifier Conf": st.column_config.NumberColumn(format="%.2f"),
                },
            )

            # ── Quick-action on selected transaction ─────────────────
            st.markdown("---")
            st.markdown("##### Quick Action")
            queue_action_ref = st.selectbox(
                "Select a transaction to act on:",
                options=sorted_df["txn_ref"].tolist(),
                key="queue_action_ref",
            )

            if queue_action_ref:
                existing = decisions.get(queue_action_ref)
                if existing:
                    st.markdown(
                        f"<span class='badge badge-decision'>"
                        f"Current: {existing['decision']} "
                        f"({existing['timestamp'][:19]})</span>",
                        unsafe_allow_html=True,
                    )

                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    if st.button("✅ Approve Match",
                                 key=f"q_approve_{queue_action_ref}",
                                 use_container_width=True):
                        save_decision(queue_action_ref, "APPROVED", report_dir)
                        st.toast(f"{queue_action_ref} approved", icon="✅")
                        st.rerun()
                with col_b:
                    if st.button("❌ Reject Match",
                                 key=f"q_reject_{queue_action_ref}",
                                 use_container_width=True):
                        save_decision(queue_action_ref, "REJECTED", report_dir)
                        st.toast(f"{queue_action_ref} rejected", icon="❌")
                        st.rerun()
                with col_c:
                    if st.button("🔎 Needs Investigation",
                                 key=f"q_investigate_{queue_action_ref}",
                                 use_container_width=True):
                        save_decision(
                            queue_action_ref, "INVESTIGATING", report_dir
                        )
                        st.toast(
                            f"{queue_action_ref} flagged for investigation",
                            icon="🔎",
                        )
                        st.rerun()

    # =================================================================
    # TAB: AUDIT TRAIL
    # =================================================================
    with tab_audit:
        st.markdown(
            '<div class="section-header">'
            'Adversarial Agent Audit Trail</div>',
            unsafe_allow_html=True,
        )

        all_refs = sorted(df_all["txn_ref"].unique().tolist())
        selected_ref = st.selectbox(
            "Select a transaction:", options=all_refs, index=0,
        )

        audit_record = next(
            (r for r in audit_trail if r.get("txn_ref") == selected_ref),
            None,
        )

        if audit_record is None:
            st.warning(f"No audit trail entry found for {selected_ref}.")
        else:
            try:
                erp_amt = float(audit_record.get("erp_amount", 0))
            except (ValueError, TypeError):
                erp_amt = 0.0
            try:
                gw_net = float(audit_record.get("gateway_net", 0))
            except (ValueError, TypeError):
                gw_net = 0.0

            v_data = audit_record.get("verifier", {})
            v_verdict = v_data.get("verdict", "N/A")

            # Existing decision
            existing = decisions.get(selected_ref)
            if existing:
                st.markdown(
                    f"<span class='badge badge-decision'>"
                    f"Your decision: {existing['decision']} "
                    f"({existing['timestamp'][:19]})</span>",
                    unsafe_allow_html=True,
                )

            # Header
            st.markdown(
                f"##### `{selected_ref}` &nbsp; "
                f"{verdict_badge_html(v_verdict)} &nbsp; "
                f"ERP: **₹{erp_amt:,.2f}** &nbsp;|&nbsp; "
                f"Gateway Net: **₹{gw_net:,.2f}**",
                unsafe_allow_html=True,
            )

            # ── Side-by-side: Matcher vs Verifier ────────────────────
            col_m, col_v = st.columns(2)

            m_data = audit_record.get("matcher", {})
            m_method = m_data.get("method", "N/A")
            m_conf = m_data.get("confidence", 0.0)
            m_proposed = m_data.get("proposed", [])
            m_reasoning = m_data.get("reasoning", "No reasoning provided.")

            with col_m:
                st.markdown(
                    '<div class="detail-card">'
                    '<div class="detail-title">🔍 Matcher (Proposer)</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**Method:** `{m_method}`")
                if len(m_proposed) == 0:
                    st.markdown("**Proposed:** `None`")
                elif len(m_proposed) == 1:
                    st.markdown(f"**Proposed:** `{m_proposed[0]}`")
                else:
                    st.markdown(
                        f"**Proposed (split):** `{', '.join(m_proposed)}`"
                    )
                st.markdown(f'**Reasoning:** *"{m_reasoning}"*')
                st.markdown("</div>", unsafe_allow_html=True)
                st.plotly_chart(
                    confidence_gauge(m_conf, "Matcher Confidence"),
                    use_container_width=True,
                )

            v_conf = v_data.get("confidence")
            if v_conf is None:
                matched_row = df_all[df_all["txn_ref"] == selected_ref]
                v_conf = (
                    float(matched_row.iloc[0]["verifier_confidence"])
                    if not matched_row.empty else 0.0
                )
            v_escalated = v_data.get("escalated_to_llm", False)
            v_reason = v_data.get(
                "reason", "No verification reasoning provided."
            )
            v_checks = v_data.get("checks", {})

            with col_v:
                st.markdown(
                    '<div class="detail-card">'
                    '<div class="detail-title">⚖️ Verifier (Auditor)</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"**Verdict:** {verdict_badge_html(v_verdict)}",
                    unsafe_allow_html=True,
                )
                st.markdown(f"**LLM Escalated:** `{v_escalated}`")
                st.markdown(f'**Reasoning:** *"{v_reason}"*')
                st.markdown("</div>", unsafe_allow_html=True)
                st.plotly_chart(
                    confidence_gauge(v_conf, "Verifier Confidence"),
                    use_container_width=True,
                )

            # ── Verification checks table ────────────────────────────
            st.markdown("###### Detailed Verification Checks")
            check_records = []
            for check_name in ["identity", "amount", "timing", "split"]:
                check_val = v_checks.get(check_name, {})
                if isinstance(check_val, dict):
                    passed = check_val.get("passed", True)
                    reason = check_val.get("reason")
                else:
                    passed = True
                    reason = check_val
                status = "🟢 Passed" if passed else "🔴 Failed/Flagged"
                detail = (
                    reason if reason
                    else "Fully satisfied policy tolerances."
                )
                check_records.append({
                    "Rule Check": check_name.capitalize(),
                    "Status": status,
                    "Audit Notes": detail,
                })
            st.table(pd.DataFrame(check_records))

            # ── Action buttons (REVIEW / EXCEPTION only) ─────────────
            if v_verdict != "RECONCILED":
                st.markdown("###### Human Review Action")
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    if st.button("✅ Approve Match",
                                 key=f"approve_{selected_ref}",
                                 use_container_width=True):
                        save_decision(selected_ref, "APPROVED", report_dir)
                        st.toast(
                            f"{selected_ref} approved", icon="✅"
                        )
                        st.rerun()
                with col_b:
                    if st.button("❌ Reject Match",
                                 key=f"reject_{selected_ref}",
                                 use_container_width=True):
                        save_decision(selected_ref, "REJECTED", report_dir)
                        st.toast(
                            f"{selected_ref} rejected", icon="❌"
                        )
                        st.rerun()
                with col_c:
                    if st.button("🔎 Needs Investigation",
                                 key=f"investigate_{selected_ref}",
                                 use_container_width=True):
                        save_decision(
                            selected_ref, "INVESTIGATING", report_dir
                        )
                        st.toast(
                            f"{selected_ref} flagged for investigation",
                            icon="🔎",
                        )
                        st.rerun()

    # =================================================================
    # TAB: POLICY
    # =================================================================
    with tab_policy:
        st.markdown(
            '<div class="section-header">Reconciliation Policy</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "These are the tolerances the matcher and verifier operate "
            "within — the AI cannot silently override these."
        )

        if policy is None:
            st.warning("policy.json not found.")
        else:
            comments = policy.get("_comments", {})
            cols = st.columns(3)
            i = 0
            for key, val in policy.items():
                if key == "_comments":
                    continue
                readable = key.replace("_", " ").title()

                if isinstance(val, bool):
                    dv = "✅ Yes" if val else "❌ No"
                elif "rupees" in key:
                    dv = f"₹{val:,.2f}"
                elif "days" in key:
                    dv = f"{val} day(s)"
                elif "confidence" in key:
                    dv = f"{val:.0%}"
                else:
                    dv = str(val)

                desc = comments.get(key, "")
                with cols[i % 3]:
                    st.metric(readable, dv, help=desc if desc else None)
                i += 1


if __name__ == "__main__":
    main()
