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
# Precise Data Extraction Helpers
# ─────────────────────────────────────────────────────────────────────────────

def to_num(val):
    """Safely convert cell value to float, handling accounting formats and units."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace(",", "").replace("₹", "").replace("Rs.", "")
    # Remove suffixes like 'Cr', 'x', '%'
    s = re.sub(r"\s*(cr|crores?|%|x|times)\.?\s*$", "", s, flags=re.I)
    # Handle negative values in parentheses (100) -> -100
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except:
        return None

def get_row_data(df, label_query):
    """
    Finds a row by searching the first column (label column) for the query string.
    Returns a list of numeric values found in that row (excluding the label).
    """
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if label_query in cell_label:
            # Extract all numeric values from the row columns (B onwards)
            row_values = [to_num(val) for val in df.iloc[r_idx, 1:]]
            # Filter out None values
            return [v for v in row_values if v is not None]
    return []

def get_latest_value(df, label_query):
    """Returns the last non-empty numeric value in a matching row."""
    series = get_row_data(df, label_query)
    return series[-1] if series else None

# ─────────────────────────────────────────────────────────────────────────────
# Python-Based Financial Computation
# ─────────────────────────────────────────────────────────────────────────────

def parse_file(file):
    try:
        # Step 1: Load "Data Sheet" specifically
        xl = pd.ExcelFile(file, engine="openpyxl")
        sheet_names = xl.sheet_names
        data_sheet_name = next((s for s in sheet_names if "data sheet" in s.lower()), None)
        
        if not data_sheet_name:
            st.error("Could not find 'Data Sheet' in the uploaded file.")
            return None
            
        df = pd.read_excel(xl, sheet_name=data_sheet_name, header=None, dtype=str)
    except Exception as e:
        st.error(f"Error loading Excel: {e}")
        return None

    data = {}

    # 2. Extract Basic Metadata
    try:
        # Usually Company name is in B1 (0,1)
        name_val = df.iloc[0, 1]
        data["company_name"] = str(name_val).strip() if pd.notna(name_val) else "Unknown"
        if data["company_name"].lower() in ["nan", "company name", "none"]:
            # Alternative: Search for a row labeled "Company Name"
            for r in range(5):
                if "company name" in str(df.iloc[r, 0]).lower():
                    data["company_name"] = str(df.iloc[r, 1]).strip()
    except:
        data["company_name"] = "Unknown"

    # Extraction of static metadata points
    data["cmp"] = get_latest_value(df, "Current Price")
    data["market_cap"] = get_latest_value(df, "Market Capitalization")

    # 3. Extract Latest Year Raw Financials (Last cell in row)
    pat = get_latest_value(df, "Net Profit")
    sales = get_latest_value(df, "Sales")
    cfo = get_latest_value(df, "Cash from Operating Activity")
    borrowings = get_latest_value(df, "Borrowings") or 0.0
    eq_cap = get_latest_value(df, "Equity Share Capital")
    reserves = get_latest_value(df, "Reserves")

    # Store series for charts
    data["pat_series"] = get_row_data(df, "Net Profit")
    data["sales_series"] = get_row_data(df, "Sales")

    # 4. Compute Ratios Dynamically in Python (Avoids reading NaN formulas)
    try:
        total_equity = None
        if eq_cap is not None and reserves is not None:
            total_equity = eq_cap + reserves

        # ROE calculation
        if total_equity and total_equity > 0 and pat is not None:
            data["roe"] = (pat / total_equity) * 100
        else:
            data["roe"] = None

        # P/E calculation
        if data["market_cap"] and pat and pat > 0:
            data["pe"] = data["market_cap"] / pat
        else:
            data["pe"] = None

        # Debt to Equity calculation
        if total_equity and total_equity > 0:
            data["de"] = borrowings / total_equity
        else:
            data["de"] = 0.0 if borrowings == 0 else None

        # CFO / PAT calculation
        if cfo is not None and pat and pat != 0:
            data["cfo_pat"] = cfo / pat
        else:
            data["cfo_pat"] = None
            
        # Free Cash Flow (CFO - Capex) - Approximated
        capex = get_latest_value(df, "Fixed assets purchased") or 0
        data["fcf"] = (cfo - abs(capex)) if cfo is not None else None

    except Exception as e:
        st.warning(f"Ratio calculation error: {e}")

    # Fallbacks for specific multi-year averages
    data["pe_5yr_avg"] = get_latest_value(df, "5 Year Avg PE") or get_latest_value(df, "Median PE")

    return data

# ─────────────────────────────────────────────────────────────────────────────
# UI Logic
# ─────────────────────────────────────────────────────────────────────────────

def run_scorecard(data, gov_ok):
    s1 = 1 if (data.get("roe") or 0) >= 15 else 0
    s2 = 1 if ((data.get("cfo_pat") or 0) >= 0.8 and (data.get("fcf") or 0) > 0) else 0
    # Step 3: Valuation check (PE within 10% of 5yr average)
    avg_pe = data.get("pe_5yr_avg") or 20
    s3 = 1 if (data.get("pe") or 100) <= (avg_pe * 1.1) else 0
    s4 = 1 if gov_ok else 0
    
    score = s1 + s2 + s3 + s4
    return {"total": score, "steps": [s1, s2, s3, s4]}

def fmt(v, d=2, sfx=""):
    return f"{v:,.{d}f}{sfx}" if v is not None else "N/A"

# ─────────────────────────────────────────────────────────────────────────────
# Main Streamlit App
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏦 Master Quantitative Risk Evaluator")
st.caption("Calculated dynamically from 'Data Sheet' raw figures.")

uploaded_file = st.file_uploader("Upload Screener.in / Safal Niveshak Excel", type="xlsx")

col1, col2 = st.columns(2)
with col1: ticker = st.text_input("Ticker Symbol", "STOCK").upper()
with col2: gov_verified = st.checkbox("Verified: 0% Pledge & Clean Audit")

if uploaded_file:
    with st.spinner("Processing Raw Financials..."):
        d = parse_file(uploaded_file)
        
    if d:
        sc = run_scorecard(d, gov_verified)
        
        # Dashboard Header
        st.header(f"🏢 {d['company_name']}")
        
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Price", fmt(d['cmp']))
        m2.metric("ROE %", fmt(d['roe'], 1, "%"))
        m3.metric("P/E Ratio", fmt(d['pe'], 1))
        m4.metric("D/E Ratio", fmt(d['de'], 2))
        m5.metric("CFO / PAT", fmt(d['cfo_pat'], 2))

        st.divider()

        # Scorecard Result
        st.subheader("Framework Scorecard")
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**Step 1: Business Quality (ROE ≥ 15%)** — {'✅ PASS' if sc['steps'][0] else '❌ FAIL'}")
            st.write(f"**Step 2: Cash Realism (CFO/PAT ≥ 0.8)** — {'✅ PASS' if sc['steps'][1] else '❌ FAIL'}")
        with c2:
            st.write(f"**Step 3: Valuation (P/E Safety)** — {'✅ PASS' if sc['steps'][2] else '❌ FAIL'}")
            st.write(f"**Step 4: Governance Verified** — {'✅ PASS' if sc['steps'][3] else '❌ FAIL'}")

        score = sc['total']
        if score == 4:
            st.success(f"### APPROVED / LOCKED IN ({score}/4)")
        elif score == 3:
            st.warning(f"### POTENTIAL / WATCHLIST ({score}/4)")
        else:
            st.error(f"### REJECTED ({score}/4)")

        # Historical Growth Expansion
        with st.expander("View Historical Raw Trends"):
            fig = go.Figure()
            if d['sales_series']:
                fig.add_trace(go.Scatter(y=d['sales_series'], name="Sales (Cr)", mode='lines+markers'))
            if d['pat_series']:
                fig.add_trace(go.Scatter(y=d['pat_series'], name="Net Profit (Cr)", mode='lines+markers'))
            fig.update_layout(title="Raw P&L Trend (10 Years)", template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

            # Raw data table
            st.table(pd.DataFrame({
                "Metric": ["Price", "Market Cap", "ROE", "P/E", "D/E", "CFO/PAT", "FCF (Cr)"],
                "Calculated Value": [fmt(d['cmp']), fmt(d['market_cap']), fmt(d['roe'], 1, "%"), 
                                     fmt(d['pe'], 1), fmt(d['de'], 2), fmt(d['cfo_pat'], 2), fmt(d['fcf'])]
            }))
