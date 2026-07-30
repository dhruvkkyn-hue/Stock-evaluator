import streamlit as st
import pandas as pd
import sqlite3
import datetime
import json
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions & UI Components
# ─────────────────────────────────────────────────────────────────────────────

def fmt(v, d=2, sfx=""):
    """Safely format numeric values. Returns 'N/A' if missing."""
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
# Page Configuration
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Master Quantitative & Business Risk Evaluator",
    page_icon="🏦",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────────────
# Data Processing Engine
# ─────────────────────────────────────────────────────────────────────────────

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        data_sheet_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not data_sheet_name:
            st.error("Could not find 'Data Sheet'.")
            return None
        df = pd.read_excel(xl, sheet_name=data_sheet_name, header=None, dtype=str)
    except Exception as e:
        st.error(f"Error loading Excel: {e}")
        return None

    data = {}
    data["company_name"] = str(df.iloc[0, 1]).strip()
    data["cmp"] = get_latest_value(df, "Current Price")
    data["market_cap"] = get_latest_value(df, "Market Capitalization")

    pat = get_latest_value(df, "Net Profit")
    cfo = get_latest_value(df, "Cash from Operating Activity")
    borrowings = get_latest_value(df, "Borrowings") or 0.0
    eq_cap = get_latest_value(df, "Equity Share Capital")
    reserves = get_latest_value(df, "Reserves")
    capex = get_latest_value(df, "Fixed assets purchased") or 0

    data["pat_series"] = get_row_data(df, "Net Profit")
    data["sales_series"] = get_row_data(df, "Sales")

    try:
        total_equity = (eq_cap + reserves) if (eq_cap is not None and reserves is not None) else None
        data["roe"] = (pat / total_equity * 100) if (total_equity and total_equity > 0 and pat) else None
        data["pe"] = (data["market_cap"] / pat) if (data["market_cap"] and pat and pat > 0) else None
        data["de"] = (borrowings / total_equity) if (total_equity and total_equity > 0) else 0.0
        data["cfo_pat"] = (cfo / pat) if (cfo is not None and pat and pat != 0) else None
        data["fcf"] = (cfo - abs(capex)) if cfo is not None else None
        data["fcf_yield"] = (data["fcf"] / data["market_cap"] * 100) if (data["fcf"] and data["market_cap"]) else None
    except: pass

    data["pe_5yr_avg"] = get_latest_value(df, "5 Year Avg PE") or get_latest_value(df, "Median PE") or 20.0
    return data

# ─────────────────────────────────────────────────────────────────────────────
# Analytical UI Logic
# ─────────────────────────────────────────────────────────────────────────────

def render_valuation_thesis(data):
    pe = data.get("pe")
    avg_pe = data.get("pe_5yr_avg")
    fcf_yield = data.get("fcf_yield")
    
    if pe and avg_pe:
        diff = ((pe / avg_pe) - 1) * 100
        desc = "premium" if diff > 0 else "discount"
        safety = "offering a significant margin of safety" if diff < -15 else "approaching fair value territory"
        if diff > 20: safety = "demanding a high growth premium which increases valuation risk"
        
        st.info(f"🔍 **Valuation Analytics:** Trading at **{fmt(pe, 1)}x P/E** ({abs(diff):.1f}% {desc} to 5-year median) with a **{fmt(fcf_yield, 1)}% FCF yield**, {safety}.")

def render_strategy_box(data, score, gov_ok):
    with st.container():
        st.markdown("### 💡 Detailed Valuation Thesis & Actionable Strategy")
        c1, c2, c3 = st.columns(3)
        
        with c1:
            st.markdown("**🛡️ The Core Value Idea**")
            if score >= 3:
                st.write(f"The business exhibits high capital efficiency (ROE: {fmt(data.get('roe'),1)}%) backed by clean cash flows. This combination suggests a 'Quality at Reasonable Price' setup where the risk of permanent capital loss is mitigated by the balance sheet strength.")
            else:
                st.write("The current setup lacks sufficient 'Moat Indicators'. The mismatch between ROE and valuation suggests the market may be overestimating the business's pricing power or ignoring structural headwinds.")

        with c2:
            st.markdown("**🚩 Analytical Risks to Watch**")
            st.write("- **Margin Sustainability:** Monitor if EBIT margins are being sustained through cost-cutting or genuine volume growth.")
            if data.get('de', 0) > 0.5:
                st.write("- **Leverage Headwinds:** High D/E ratio could impact net profitability in a rising interest rate environment.")
            st.write("- **Working Capital:** Watch for any divergence between PAT growth and CFO growth over the next 2 quarters.")

        with c3:
            st.markdown("**🎯 Investor Action Plan**")
            st.write(f"1. **Peer Benchmarking:** Compare {data.get('company_name')}'s FCF yield against the sector leader.")
            st.write("2. **Growth Sanity Check:** Verify if the Revenue 3-year CAGR exceeds 12% to justify the P/E.")
            st.write("3. **Allocation:** If approved, consider a staggered entry (SIP) to benefit from potential valuation mean-reversion.")

# ─────────────────────────────────────────────────────────────────────────────
# Main Streamlit UI
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏦 Master Quantitative & Business Risk Evaluator")
st.markdown("---")

uploaded_file = st.file_uploader("Upload Screener.in Excel", type="xlsx")

col_t, col_g, col_b = st.columns(3)
with col_t: ticker = st.text_input("Ticker Symbol", "STOCK").upper()
with col_g: gov_verified = st.checkbox("Governance Verified (0% Pledge / Clean Audit)")
with col_b: beta = st.number_input("Stock Beta", 0.0, 5.0, 1.1)

if uploaded_file:
    data = parse_file(uploaded_file)
    if data:
        st.header(f"🏢 {data.get('company_name', 'Unknown Company')}")
        
        # Dashboard
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Current Price", f"₹{fmt(data.get('cmp'))}")
        m2.metric("ROE %", fmt(data.get('roe'), 1, "%"), help="Capital Efficiency Indicator")
        m3.metric("P/E Ratio", fmt(data.get('pe'), 1), help="Valuation Multiple")
        m4.metric("D/E Ratio", fmt(data.get('de'), 2), help="Balance Sheet Risk")
        m5.metric("FCF Yield %", fmt(data.get('fcf_yield'), 1, "%"), help="Cash return for every ₹100 of Market Cap")

        # 1. New Dynamic Valuation Analytics
        render_valuation_thesis(data)
        
        # 2. Scorecard Logic
        s1_pass = (data.get("roe") or 0) >= 15
        s2_pass = (data.get("cfo_pat") or 0) >= 0.8 and (data.get("fcf") or 0) > 0
        s3_pass = (data.get("pe") or 100) <= (data.get("pe_5yr_avg") or 20) * 1.1
        score = sum([s1_pass, s2_pass, s3_pass, gov_verified])

        st.markdown("---")
        
        # 3. Enhanced Strategy Section
        render_strategy_box(data, score, gov_verified)
        
        st.markdown("---")
        
        # 4. Standard Framework Breakdown
        st.subheader("🎯 Master Framework Scorecard")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.write(f"**Step 1: Quality (ROE ≥ 15%)** — {'✅' if s1_pass else '❌'}")
            st.write(f"**Step 2: Cash Realism (CFO/PAT ≥ 0.8)** — {'✅' if s2_pass else '❌'}")
        with col_s2:
            st.write(f"**Step 3: Valuation Safety** — {'✅' if s3_pass else '❌'}")
            st.write(f"**Step 4: Governance Verified** — {'✅' if gov_verified else '❌'}")

        if score == 4:
            st.success(f"### APPROVED: High Conviction Portfolio Candidate ({score}/4)")
        elif score == 3:
            st.warning(f"### MONITOR: Quality Business at Stretched Price ({score}/4)")
        else:
            st.error(f"### REJECTED: Inadequate Risk-Reward Ratio ({score}/4)")

        # 5. Charts
        if data.get('sales_series'):
            with st.expander("📈 Historical Revenue & Profit Context"):
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data.get('sales_series'), name="Revenue (Cr)", line=dict(color='#00CC96', width=3)))
                fig.add_trace(go.Scatter(y=data.get('pat_series'), name="Net Profit (Cr)", line=dict(color='#636EFA', width=3)))
                fig.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=30, b=20))
                st.plotly_chart(fig, use_container_width=True)
