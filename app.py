import streamlit as st
import pandas as pd
import sqlite3
import os
import datetime
import json
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions (Defined first to prevent NameErrors)
# ─────────────────────────────────────────────────────────────────────────────

def fmt(v, d=2, sfx=""):
    """Safely format numeric values for the UI. Returns 'N/A' if value is None."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    try:
        return f"{float(v):,.{d}f}{sfx}"
    except (ValueError, TypeError):
        return "N/A"

def to_num(val):
    """Safely convert cell value to float, handling accounting formats and units."""
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
# Page Configuration
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Master Quantitative & Business Risk Evaluator",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# DB Initialization
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
# Financial Computation Engine
# ─────────────────────────────────────────────────────────────────────────────

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
    try:
        data["company_name"] = str(df.iloc[0, 1]).strip()
        if data["company_name"].lower() in ["nan", "company name", "none"]:
            for r in range(5):
                if "company name" in str(df.iloc[r, 0]).lower():
                    data["company_name"] = str(df.iloc[r, 1]).strip()
    except: data["company_name"] = "Unknown"

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
    except: pass

    data["pe_5yr_avg"] = get_latest_value(df, "5 Year Avg PE") or get_latest_value(df, "Median PE") or 20.0
    return data

# ─────────────────────────────────────────────────────────────────────────────
# Narrative Engine
# ─────────────────────────────────────────────────────────────────────────────

def get_insight(metric_name, value, threshold=None):
    if value is None: return "Insufficient data to analyze this metric."
    if metric_name == "ROE":
        if value >= 15: return "✅ **Solid efficiency.** The business creates healthy value for shareholders."
        return "⚠️ **Weak efficiency.** Returns on capital are below the 15% benchmark."
    if metric_name == "CFO_PAT":
        if value >= 0.8: return "✅ **Healthy conversion.** Profits are largely backed by actual cash inflows."
        return "🚩 **Earnings Quality Warning.** Reported profits are significantly higher than cash collected."
    if metric_name == "VALUATION":
        if value <= threshold: return f"✅ **Attractive valuation.** Trading below the 5-year average P/E."
        return f"🚩 **Stretched valuation.** Trading higher than the 5-year historical norm."
    return ""

def generate_summary(data, score):
    company = data.get('company_name', 'The company')
    if score == 4:
        return "🚀 Strong Compounder", f"{company} is high-quality and fairly valued.", "Next Step: Primary buy candidate.", "success"
    elif score == 3:
        return "⚖️ Quality with Caveats", f"{company} is strong but fails one critical check.", "Next Step: Monitor for correction.", "warning"
    return "⚠️ High Risk / Avoid", f"{company} currently fails multiple safety checks.", "Next Step: Pass for now.", "error"

# ─────────────────────────────────────────────────────────────────────────────
# Main Interface
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏦 Master Quantitative Risk Evaluator")
st.markdown("---")

uploaded_file = st.file_uploader("Upload Screener.in Excel", type="xlsx")

col_t, col_g, col_b = st.columns(3)
with col_t: ticker = st.text_input("Ticker Symbol", "STOCK").upper()
with col_g: gov_verified = st.checkbox("Governance Verified")
with col_b: beta = st.number_input("Stock Beta", 0.0, 5.0, 1.1)

if uploaded_file:
    data = parse_file(uploaded_file)
    if data:
        # 1. Header & Metrics (Fixed NameError using 'data' and .get())
        st.header(f"🏢 {data.get('company_name', 'Unknown Company')}")
        
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Current Price", f"₹{fmt(data.get('cmp'))}", help="The latest price.")
        m2.metric("ROE %", fmt(data.get('roe'), 1, "%"), help="Target: >15%.")
        m3.metric("P/E Ratio", fmt(data.get('pe'), 1), help="Price to Earnings.")
        m4.metric("D/E Ratio", fmt(data.get('de'), 2), help="Target: <0.5.")
        m5.metric("CFO / PAT", fmt(data.get('cfo_pat'), 2), help="Target: >0.8.")

        # 2. Scorecard Logic
        s1_pass = (data.get("roe") or 0) >= 15
        s2_pass = (data.get("cfo_pat") or 0) >= 0.8 and (data.get("fcf") or 0) > 0
        s3_pass = (data.get("pe") or 100) <= (data.get("pe_5yr_avg") or 20) * 1.1
        score = sum([s1_pass, s2_pass, s3_pass, gov_verified])

        st.subheader("🎯 Master Scorecard")
        with st.expander(f"Step 1: Business Quality — {'✅' if s1_pass else '❌'}"):
            st.write(get_insight("ROE", data.get("roe")))
        with st.expander(f"Step 2: Cash Realism — {'✅' if s2_pass else '❌'}"):
            st.write(get_insight("CFO_PAT", data.get("cfo_pat")))
        with st.expander(f"Step 3: Valuation — {'✅' if s3_pass else '❌'}"):
            st.write(get_insight("VALUATION", data.get("pe"), data.get("pe_5yr_avg")))
        with st.expander(f"Step 4: Governance — {'✅' if gov_verified else '❌'}"):
            st.write("✅ Verified" if gov_verified else "❌ Pending verification")

        st.markdown("---")

        # 3. Summary
        title, body, nxt, status = generate_summary(data, score)
        if status == "success": st.success(f"### {title}\n{body}\n**{nxt}**")
        elif status == "warning": st.warning(f"### {title}\n{body}\n**{nxt}**")
        else: st.error(f"### {title}\n{body}\n**{nxt}**")

        # 4. Chart
        if data.get('sales_series') or data.get('pat_series'):
            with st.expander("📈 Growth Trends"):
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data.get('sales_series'), name="Sales"))
                fig.add_trace(go.Scatter(y=data.get('pat_series'), name="Profit"))
                st.plotly_chart(fig, use_container_width=True)
