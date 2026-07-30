import streamlit as st
import pandas as pd
import sqlite3
import os
import datetime
import json
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# Page Configuration & UI Helpers
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Master Quantitative & Business Risk Evaluator",
    page_icon="🏦",
    layout="wide",
)

def fmt(v, d=2, sfx=""):
    """Safely format numeric values for the UI. Returns 'N/A' if missing."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    try:
        return f"{float(v):,.{d}f}{sfx}"
    except (ValueError, TypeError):
        return "N/A"

def to_num(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace(",", "").replace("₹", "").replace("Rs.", "")
    s = re.sub(r"\s*(cr|crores?|%|x|times)\.?\s*$", "", s, flags=re.I)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# Extraction & Calculation Engine
# ─────────────────────────────────────────────────────────────────────────────

def get_row_data(df, label_query):
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if label_query in cell_label:
            return [to_num(val) for val in df.iloc[r_idx, 1:] if to_num(val) is not None]
    return []

def get_latest_value(df, label_query):
    series = get_row_data(df, label_query)
    return series[-1] if series else None

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name: return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
    except: return None

    data = {}
    data["company_name"] = str(df.iloc[0, 1]).strip()
    data["cmp"] = get_latest_value(df, "Current Price")
    data["market_cap"] = get_latest_value(df, "Market Capitalization")
    
    pat = get_latest_value(df, "Net Profit")
    cfo = get_latest_value(df, "Cash from Operating Activity")
    eq_cap = get_latest_value(df, "Equity Share Capital")
    reserves = get_latest_value(df, "Reserves")
    borrowings = get_latest_value(df, "Borrowings") or 0.0
    capex = get_latest_value(df, "Fixed assets purchased") or 0

    data["pat_series"] = get_row_data(df, "Net Profit")
    data["sales_series"] = get_row_data(df, "Sales")

    try:
        total_equity = (eq_cap + reserves) if (eq_cap and reserves) else None
        data["roe"] = (pat / total_equity * 100) if (total_equity and pat) else None
        data["pe"] = (data["market_cap"] / pat) if (data["market_cap"] and pat and pat > 0) else None
        data["de"] = (borrowings / total_equity) if total_equity else 0.0
        data["cfo_pat"] = (cfo / pat) if (cfo and pat and pat != 0) else None
        
        # Free Cash Flow Calculation
        data["fcf_val"] = (cfo - abs(capex)) if cfo is not None else None
        data["fcf_yield"] = (data["fcf_val"] / data["market_cap"] * 100) if (data["fcf_val"] and data["market_cap"]) else 0.0
    except: pass

    data["pe_5yr_avg"] = get_latest_value(df, "5 Year Avg PE") or get_latest_value(df, "Median PE") or 20.0
    return data

# ─────────────────────────────────────────────────────────────────────────────
# Main Streamlit UI
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏦 Master Quantitative & Business Risk Evaluator")
st.caption("A Conviction-Based Framework for Indian Equities")

uploaded_file = st.file_uploader("Upload Screener.in / Safal Niveshak Excel", type="xlsx")

col_t, col_g, col_b = st.columns(3)
with col_t: ticker = st.text_input("Ticker Symbol", "STOCK").upper()
with col_g: gov_verified = st.checkbox("Governance Shield Verified (0% Pledging & Clean Audit)")
with col_b: beta = st.number_input("Stock Beta", 0.0, 5.0, 1.1)

if uploaded_file:
    data = parse_file(uploaded_file)
    if data:
        st.header(f"🏢 {data.get('company_name', 'Unknown Company')}")
        
        # 1. Top-Level Metric Dashboard with tooltips
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Current Price", f"₹{fmt(data.get('cmp'))}", help="The latest market price per share.")
        m2.metric("ROE %", fmt(data.get('roe'), 1, "%"), help="Return on Equity: Measures management's ability to generate profits from shareholders' capital. Target >15%.")
        m3.metric("P/E Ratio", fmt(data.get('pe'), 1), help="Price-to-Earnings: How many years of earnings you are paying to buy the business.")
        m4.metric("D/E Ratio", fmt(data.get('de'), 2), help="Debt-to-Equity: Financial leverage. Ideally <0.5 for stability.")
        m5.metric("FCF Yield %", fmt(data.get('fcf_yield'), 1, "%"), help="Free Cash Flow Yield: The actual cash return generated by the business relative to its market cap.")

        st.markdown("---")

        # 2. FrameWork Scorecard with Narrative
        st.subheader("🎯 Master Framework Scorecard")
        
        s1_pass = (data.get("roe") or 0) >= 15
        s2_pass = (data.get("cfo_pat") or 0) >= 0.8 and (data.get("fcf_val") or 0) > 0
        s3_pass = (data.get("pe") or 100) <= (data.get("pe_5yr_avg") or 20) * 1.1
        
        # UI Outputs for Scorecard
        with st.expander(f"Step 1: Business Quality (ROE) — {'✅ PASS' if s1_pass else '❌ FAIL'}", expanded=True):
            if s1_pass: st.write(f"Strong capital efficiency at {fmt(data.get('roe'), 1)}%. The business demonstrates a high return on retained earnings.")
            else: st.write(f"The ROE of {fmt(data.get('roe'), 1)}% is below the quality threshold, suggesting a potential lack of competitive moat.")

        with st.expander(f"Step 2: Cash Realism (CFO/PAT) — {'✅ PASS' if s2_pass else '❌ FAIL'}", expanded=True):
            if s2_pass: st.write(f"Clean accounting confirmed. A CFO/PAT of {fmt(data.get('cfo_pat'), 2)} indicates reported profits are fully backed by cash.")
            else: st.write("Warning: Reported profits are not translating into cash flow. Scrutinize the working capital and receivables.")

        with st.expander(f"Step 3: Valuation Safety — {'✅ PASS' if s3_pass else '❌ FAIL'}", expanded=True):
            pe = data.get('pe') or 0
            yield_fcf = data.get('fcf_yield') or 0
            st.info(f"**Thesis:** Trading at **{pe:.1f}x P/E** with an estimated **Free Cash Flow Yield of {yield_fcf:.1f}%**, { 'offering a strong margin of safety' if s3_pass else 'suggesting a premium valuation price' }.")

        with st.expander(f"Step 4: Governance Shield — {'✅ PASS' if gov_verified else '❌ FAIL'}"):
            if gov_verified: st.write("Governance check complete: No pledging and clean audit history.")
            else: st.write("Governance check pending: Manual verification of pledging and audit report is required.")

        # 3. COMPREHENSIVE ANALYSIS CONTAINER (The "Core Thesis")
        st.markdown("---")
        with st.container():
            st.subheader("💡 Comprehensive Investment Thesis & Action Plan")
            
            c_a, c_b, c_c = st.columns(3)
            
            with c_a:
                st.markdown("### 🎯 The Core Value Idea")
                roe_val = data.get('roe', 0)
                cp_val = data.get('cfo_pat', 0)
                if roe_val >= 15 and cp_val >= 0.8:
                    st.write(f"The fundamental thesis rests on **exceptional capital efficiency** ({roe_val:.1f}% ROE) combined with **high earnings quality**. Because the company generates surplus cash (CFO/PAT: {cp_val:.2f}), it can fund its own growth without diluting shareholders or taking on toxic debt.")
                else:
                    st.write("The core value proposition is currently **under pressure**. Either the returns on capital are mediocre, or the earnings quality is suspect due to poor cash conversion. This setup requires significant margin of safety to justify entry.")

            with c_b:
                st.markdown("### ⚠️ Key Analytical Risks")
                # Dynamic risk flagging
                de_val = data.get('de', 0)
                cp_val = data.get('cfo_pat', 0)
                if de_val > 0.5: st.warning(f"**Debt Trend:** D/E is {de_val:.2f}. Monitor interest coverage to ensure debt doesn't eat into net margins.")
                if cp_val < 1.0: st.info(f"**Working Capital:** CFO/PAT is {cp_val:.2f}. Check if money is getting locked up in inventory or unpaid bills (receivables).")
                if de_val <= 0.5 and cp_val >= 1.0: st.success("No immediate financial risks detected in leverage or cash conversion cycles.")

            with c_c:
                st.markdown("### 📋 Actionable Next Steps")
                st.write("1. **Verify Revenue Momentum:** Check the 3-Year Historical Revenue CAGR on Screener to ensure the business is still expanding.")
                st.write(f"2. **Peer Benchmarking:** Compare the current **{data.get('pe',0):.1f}x P/E** against direct industry competitors to detect overvaluation.")
                st.write("3. **Margin Stability:** Review the 'Profit & Loss' tab to ensure Operating Profit Margins (OPM) have been stable or improving over 5 years.")

        # 4. Growth Trends (Charts)
        st.markdown("---")
        with st.expander("📈 Historical Growth Context (Sales vs Profit)"):
            if data.get('sales_series') and data.get('pat_series'):
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data['sales_series'], name="Sales (Cr)", line=dict(color='#00CC96', width=3)))
                fig.add_trace(go.Scatter(y=data['pat_series'], name="Net Profit (Cr)", line=dict(color='#636EFA', width=3)))
                fig.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=30, b=20))
                st.plotly_chart(fig, use_container_width=True)
