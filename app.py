import streamlit as st
import pandas as pd
import sqlite3
import os
import datetime
import json
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# Page Configuration
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Master Quantitative & Business Risk Evaluator",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants & DB Initialization
# ─────────────────────────────────────────────────────────────────────────────
DB_PATH = "evaluations.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, saved_at TEXT, company_name TEXT, ticker TEXT,
                cmp REAL, market_cap REAL, roe REAL, cfo_pat REAL, de_ratio REAL, pe_current REAL,
                total_score INTEGER, verdict TEXT, narrative TEXT
            )""")

init_db()

# ─────────────────────────────────────────────────────────────────────────────
# Precision Data Extraction Helpers (Raw "Data Sheet" Extraction)
# ─────────────────────────────────────────────────────────────────────────────

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

def get_row_data(df, label_query):
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if label_query in cell_label:
            row_values = [to_num(val) for val in df.iloc[r_idx, 1:]]
            return [v for v in row_values if v is not None]
    return []

def get_latest_value(df, label_query):
    series = get_row_data(df, label_query)
    return series[-1] if series else None

# ─────────────────────────────────────────────────────────────────────────────
# Financial Computation Engine
# ─────────────────────────────────────────────────────────────────────────────

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        data_sheet_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not data_sheet_name:
            st.error("Could not find 'Data Sheet' in the uploaded file.")
            return None
        df = pd.read_excel(xl, sheet_name=data_sheet_name, header=None, dtype=str)
    except Exception as e:
        st.error(f"Error loading Excel: {e}")
        return None

    data = {}
    # Metadata
    try:
        data["company_name"] = str(df.iloc[0, 1]).strip()
        if data["company_name"].lower() in ["nan", "company name", "none"]:
            for r in range(5):
                if "company name" in str(df.iloc[r, 0]).lower():
                    data["company_name"] = str(df.iloc[r, 1]).strip()
    except: data["company_name"] = "Unknown"

    data["cmp"] = get_latest_value(df, "Current Price")
    data["market_cap"] = get_latest_value(df, "Market Capitalization")

    # Raw Financials
    pat = get_latest_value(df, "Net Profit")
    cfo = get_latest_value(df, "Cash from Operating Activity")
    borrowings = get_latest_value(df, "Borrowings") or 0.0
    eq_cap = get_latest_value(df, "Equity Share Capital")
    reserves = get_latest_value(df, "Reserves")
    capex = get_latest_value(df, "Fixed assets purchased") or 0

    data["pat_series"] = get_row_data(df, "Net Profit")
    data["sales_series"] = get_row_data(df, "Sales")

    # Ratio Computation
    try:
        total_equity = (eq_cap + reserves) if (eq_cap is not None and reserves is not None) else None
        data["roe"] = (pat / total_equity * 100) if (total_equity and total_equity > 0 and pat) else None
        data["pe"] = (data["market_cap"] / pat) if (data["market_cap"] and pat and pat > 0) else None
        data["de"] = (borrowings / total_equity) if (total_equity and total_equity > 0) else 0.0
        data["cfo_pat"] = (cfo / pat) if (cfo is not None and pat and pat != 0) else None
        data["fcf"] = (cfo - abs(capex)) if cfo is not None else None
    except: pass

    data["pe_5yr_avg"] = get_latest_value(df, "5 Year Avg PE") or get_latest_value(df, "Median PE") or 20.0
    return data

# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Narrative Engine
# ─────────────────────────────────────────────────────────────────────────────

def get_insight(metric_name, value, threshold=None):
    if value is None: return "Insufficient data to analyze this metric."
    
    if metric_name == "ROE":
        if value >= 20: return "✨ **Exceptional efficiency.** The business generates massive returns on shareholder capital, suggesting a strong moat."
        if value >= 15: return "✅ **Solid efficiency.** The business creates healthy value for shareholders, meeting the quality threshold."
        return "⚠️ **Weak efficiency.** Returns on capital are below the 15% benchmark; the business may lack a competitive advantage."

    if metric_name == "CFO_PAT":
        if value >= 1.0: return "✨ **Outstanding cash conversion.** The company collects more cash than it reports as profit. High earnings quality."
        if value >= 0.8: return "✅ **Healthy conversion.** Profits are largely backed by actual cash inflows. Clean accounting."
        return "🚩 **Earnings Quality Warning.** Reported profits are significantly higher than cash collected. Scrutinize receivables."

    if metric_name == "VALUATION":
        # threshold is the 5yr Avg PE
        if value <= threshold: return f"✅ **Attractive valuation.** Trading below the 5-year average P/E of {threshold:.1f}x."
        if value <= threshold * 1.15: return f"🟡 **Fairly valued.** Trading at a slight premium to the historical average."
        return f"🚩 **Stretched valuation.** Trading significantly higher than the 5-year historical norm."

    return ""

def generate_summary(data, score):
    company = data.get('company_name', 'This company')
    roe = data.get('roe', 0) or 0
    cfo_pat = data.get('cfo_pat', 0) or 0
    pe = data.get('pe', 0) or 0
    avg_pe = data.get('pe_5yr_avg', 20) or 20
    
    if score == 4:
        title = "🚀 Executive Summary: Strong Compounder"
        body = f"{company} is a high-quality business with an ROE of {roe:.1f}% and excellent cash conversion. It currently offers a margin of safety as its valuation is aligned with historical norms."
        next_step = "Next Step: Deep dive into management commentary and sector tailwinds. This is a primary buy candidate."
        status = "success"
    elif score == 3:
        title = "⚖️ Executive Summary: Quality with Caveats"
        body = f"{company} shows strong fundamentals but fails one critical test—likely either stretched valuation or a slight dip in cash conversion. The underlying ROE of {roe:.1f}% remains attractive."
        next_step = "Next Step: Identify which check failed. If it's valuation, wait for a 10-15% correction. If it's cash flow, investigate the working capital cycle."
        status = "warning"
    else:
        title = "⚠️ Executive Summary: High Risk / Avoid"
        body = f"{company} currently fails multiple safety checks. With an ROE of {roe:.1f}% or poor cash conversion, the business model may be under stress or poorly managed."
        next_step = "Next Step: Pass on this stock for now. Re-evaluate only if ROE crosses 15% and CFO/PAT improves."
        status = "error"
    
    return title, body, next_step, status

# ─────────────────────────────────────────────────────────────────────────────
# UI Implementation
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏦 Master Quantitative Risk Evaluator")
st.markdown("---")

uploaded_file = st.file_uploader("Upload Screener.in / Safal Niveshak Excel", type="xlsx", help="Upload the multi-sheet Excel export from Screener.in")

col_t, col_g, col_b = st.columns(3)
with col_t: ticker = st.text_input("Ticker Symbol", "STOCK").upper()
with col_g: gov_verified = st.checkbox("Governance Verified", help="Check this if you have verified 0% promoter pledging and no major audit red flags.")
with col_b: beta = st.number_input("Stock Beta", 0.0, 5.0, 1.1, help="Beta around 1.1 (±0.3) is ideal for this framework.")

if uploaded_file:
    d = parse_file(uploaded_file)
    if d:
        # 1. Dashboard Metrics
        st.header(f"🏢 {d['company_name']}")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Current Price", f"₹{fmt(d['cmp'])}", help="The latest traded price of the stock.")
        m2.metric("ROE %", fmt(d['roe'], 1, "%"), help="Return on Equity: Measures how effectively management uses shareholder money to generate profit. Target: >15%.")
        m3.metric("P/E Ratio", fmt(d['pe'], 1), help="Price to Earnings: How much you pay for ₹1 of profit. Compare this to the 5Y Average.")
        m4.metric("D/E Ratio", fmt(d['de'], 2), help="Debt to Equity: Measures financial leverage. Ideally should be <0.5 for safety.")
        m5.metric("CFO / PAT", fmt(d['cfo_pat'], 2), help="Cash Flow from Operations divided by Net Profit. Measures earnings quality. Target: >0.8.")

        # 2. Scorecard with Insights
        st.subheader("🎯 4-Step Master Scorecard")
        
        # Logic
        s1_pass = (d.get("roe") or 0) >= 15
        s2_pass = (d.get("cfo_pat") or 0) >= 0.8 and (d.get("fcf") or 0) > 0
        s3_pass = (d.get("pe") or 100) <= (d.get("pe_5yr_avg") or 20) * 1.1
        score = sum([s1_pass, s2_pass, s3_pass, gov_verified])

        # Step 1: ROE
        with st.expander(f"Step 1: Business Quality (ROE) — {'✅ PASS' if s1_pass else '❌ FAIL'}", expanded=True):
            st.write(get_insight("ROE", d.get("roe")))
        
        # Step 2: CFO/PAT
        with st.expander(f"Step 2: Cash Realism (CFO/PAT) — {'✅ PASS' if s2_pass else '❌ FAIL'}", expanded=True):
            st.write(get_insight("CFO_PAT", d.get("cfo_pat")))
            if (d.get("fcf") or 0) <= 0: st.write("⚠️ **Note:** Free Cash Flow is negative; the company is spending more on Capex than it earns in operating cash.")

        # Step 3: Valuation
        with st.expander(f"Step 3: Valuation Safety — {'✅ PASS' if s3_pass else '❌ FAIL'}", expanded=True):
            st.write(get_insight("VALUATION", d.get("pe"), d.get("pe_5yr_avg")))

        # Step 4: Governance
        with st.expander(f"Step 4: Governance Shield — {'✅ PASS' if gov_verified else '❌ FAIL'}", expanded=True):
            if gov_verified: st.write("✅ **Trust established.** Manual verification confirms clean audit and zero pledging.")
            else: st.write("❌ **Pending Verification.** You must check Screener.in for 'Promoter Pledging' and audit qualifications.")

        st.markdown("---")

        # 3. Executive Summary Card
        title, body, next_step, status = generate_summary(d, score)
        if status == "success": st.success(f"### {title}\n\n{body}\n\n**{next_step}**")
        elif status == "warning": st.warning(f"### {title}\n\n{body}\n\n**{next_step}**")
        else: st.error(f"### {title}\n\n{body}\n\n**{next_step}**")

        # 4. Visualization
        with st.expander("📈 View 10-Year Growth Trends"):
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=d['sales_series'], name="Sales", line=dict(color='#00CC96')))
            fig.add_trace(go.Scatter(y=d['pat_series'], name="Net Profit", line=dict(color='#636EFA')))
            fig.update_layout(title="Sales vs Profit (Raw Cr)", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

def fmt(v, d=2, sfx=""):
    return f"{v:,.{d}f}{sfx}" if v is not None else "N/A"
