import streamlit as st
import pandas as pd
import sqlite3
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. ROBUST NUMERIC HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def safe_num(val, default=0.0):
    """Safely converts any value to a float, preventing TypeError/NoneType errors."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def fmt(v, d=2, sfx=""):
    """Formatted UI output. Returns 'N/A' for missing data."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    try:
        return f"{float(v):,.{d}f}{sfx}"
    except (ValueError, TypeError):
        return "N/A"

def to_num(val):
    """Cleans Screener strings (currency, suffixes, parentheses) into floats."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace(",", "").replace("₹", "").replace("Rs.", "")
    s = re.sub(r"\s*(cr|crores?|%|x|times|inr)\.?\s*$", "", s, flags=re.I)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 2. RAW DATA EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_row_series(df, label_query):
    """Finds row by keyword and returns all numeric values in that row."""
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if label_query in cell_label:
            return [to_num(val) for val in df.iloc[r_idx, 1:] if to_num(val) is not None]
    return []

def get_latest(df, labels):
    """Searches multiple label aliases and returns the last numeric value found."""
    if isinstance(labels, str): labels = [labels]
    for label in labels:
        series = get_row_series(df, label)
        if series:
            return series[-1]
    return None

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Target sheet 'Data Sheet' not found in Excel.")
            return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
    except Exception as e:
        st.error(f"File Processing Error: {e}")
        return None

    data = {}
    data["company_name"] = str(df.iloc[0, 1]).strip()
    
    # --- RAW LINE ITEM EXTRACTION ---
    # P&L Items
    sales = get_latest(df, ["Sales", "Revenue"])
    ebit = get_latest(df, ["Operating Profit", "EBIT"])
    pat = get_latest(df, ["Net Profit", "Profit after tax"])
    cfo = get_latest(df, ["Cash from Operating Activity", "CFO"])
    
    # Balance Sheet Items
    share_cap = get_latest(df, ["Equity Share Capital", "Share Capital"])
    reserves = get_latest(df, "Reserves")
    borrowings = get_latest(df, ["Borrowings", "Total Debt"]) or 0.0
    other_liab = get_latest(df, ["Other Liabilities", "Other Liab"]) or 0.0
    cash = get_latest(df, ["Cash Equivalents", "Cash & Bank"]) or 0.0
    capex = get_latest(df, ["Fixed assets purchased", "Capital Expenditure"]) or 0.0
    
    # Metadata
    data["cmp"] = get_latest(df, "Current Price")
    data["market_cap"] = get_latest(df, "Market Capitalization")
    data["pe_5yr_avg"] = get_latest(df, ["5 Year Avg PE", "Median PE"]) or 20.0

    # --- DYNAMIC DERIVATIONS ---
    try:
        # 1. Balance Sheet Derivation
        total_equity = safe_num(share_cap) + safe_num(reserves)
        total_assets = total_equity + safe_num(borrowings) + safe_num(other_liab)
        invested_capital = total_equity + safe_num(borrowings) - safe_num(cash)
        
        # 2. Ratio Calculations
        data["roe"] = (safe_num(pat) / total_equity * 100) if total_equity > 0 else 0.0
        data["de"] = (safe_num(borrowings) / total_equity) if total_equity > 0 else 0.0
        data["pe"] = (safe_num(data["market_cap"]) / safe_num(pat)) if safe_num(pat) > 0 else 0.0
        data["cfo_pat"] = (safe_num(cfo) / safe_num(pat)) if safe_num(pat) > 0 else 0.0
        
        # 3. Moat & Efficiency Metrics
        data["asset_turnover"] = (safe_num(sales) / total_assets) if total_assets > 0 else 0.0
        data["equity_multiplier"] = (total_assets / total_equity) if total_equity > 0 else 0.0
        
        nopat = safe_num(ebit) * 0.75 # Assuming 25% tax
        data["roic"] = (nopat / invested_capital * 100) if invested_capital > 0 else 0.0
        
        # 4. Reinvestment & Compounding
        # Note: Capex is usually recorded as a negative cash flow; use abs()
        actual_capex = abs(safe_num(capex))
        data["reinvestment_rate"] = (actual_capex / nopat * 100) if nopat > 0 else 0.0
        data["compounding_rate"] = (data["roic"] / 100) * data["reinvestment_rate"]
        data["fcf"] = safe_num(cfo) - actual_capex

        # For Charts
        data["sales_series"] = get_row_series(df, "Sales")
        data["pat_series"] = get_row_series(df, "Net Profit")

    except Exception as e:
        st.warning(f"Metric derivation incomplete: {e}")

    return data

# ─────────────────────────────────────────────────────────────────────────────
# 3. STREAMLIT INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Institutional Value Terminal", layout="wide")
st.title("🏦 Master Quantitative & Moat Evaluator")

with st.sidebar:
    st.header("Analysis Settings")
    ticker = st.text_input("Ticker Symbol", "STOCK").upper()
    gov_ok = st.checkbox("Governance Verified (0% Pledging)")
    beta_val = st.number_input("Stock Beta", value=1.1, step=0.1)

up = st.file_uploader("Upload Screener 'Data Sheet' Excel", type="xlsx")

if up:
    data = parse_file(up)
    if data:
        # Dashboard Header
        st.header(f"🏢 {data.get('company_name')}")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Current Price", f"₹{fmt(data.get('cmp'))}")
        m2.metric("Market Cap (Cr)", fmt(data.get('market_cap'), 0))
        m3.metric("ROE %", fmt(data.get('roe'), 1, "%"))
        m4.metric("D/E Ratio", fmt(data.get('de'), 2))
        m5.metric("P/E Ratio", fmt(data.get('pe'), 1))

        # --- DYNAMIC MOAT SECTION ---
        st.markdown("---")
        st.subheader("🏰 Economic Moat & Capital Efficiency Analysis")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Core Efficiency**")
            roic = data.get("roic", 0)
            st.metric("ROIC (Return on Invested Capital)", fmt(roic, 1, "%"))
            if roic >= 20: st.success("🏰 Wide Moat: Superior capital returns.")
            elif roic >= 12: st.info("🛡️ Narrow Moat: Moderate advantage.")
            else: st.error("⚠️ No Moat: Returns below cost of capital.")

        with c2:
            st.markdown("**DuPont Decomposition**")
            st.write(f"**Asset Turnover:** {fmt(data.get('asset_turnover'), 2)}x")
            st.write(f"**Equity Multiplier:** {fmt(data.get('equity_multiplier'), 2)}x")
            if safe_num(data.get("equity_multiplier")) > 2.5:
                st.warning("⚠️ ROE is debt-inflated.")
            else:
                st.success("✅ ROE is quality-driven.")

        with c3:
            st.markdown("**Compounding Runway**")
            st.write(f"**Reinvestment Rate:** {fmt(data.get('reinvestment_rate'), 1)}%")
            st.write(f"**Compounding Rate:** {fmt(data.get('compounding_rate'), 1)}%")
            if safe_num(data.get('compounding_rate')) > 10:
                st.success("🚀 High Compounding Potential")

        # --- SCORECARD ---
        st.markdown("---")
        st.subheader("🎯 Master Framework Scorecard")
        
        s1 = data.get("roe", 0) >= 15
        s2 = data.get("cfo_pat", 0) >= 0.8 and data.get("fcf", 0) > 0
        s3 = data.get("pe", 100) <= (data.get("pe_5yr_avg", 20) * 1.1)
        score = sum([s1, s2, s3, gov_ok])

        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.write(f"**1. Quality (ROE):** {'✅' if s1 else '❌'}")
        sc2.write(f"**2. Cash Realism:** {'✅' if s2 else '❌'}")
        sc3.write(f"**3. Valuation:** {'✅' if s3 else '❌'}")
        sc4.write(f"**4. Governance:** {'✅' if gov_ok else '❌'}")

        if score == 4: st.success(f"### APPROVED ({score}/4)")
        elif score == 3: st.warning(f"### WATCHLIST ({score}/4)")
        else: st.error(f"### REJECTED ({score}/4)")

        # --- CHARTS ---
        st.markdown("---")
        if data.get("sales_series"):
            with st.expander("📈 Historical Context (10-Year Trend)"):
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data["sales_series"], name="Sales", line=dict(color="#00CC96")))
                fig.add_trace(go.Scatter(y=data["pat_series"], name="Net Profit", line=dict(color="#636EFA")))
                fig.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=30, b=20))
                st.plotly_chart(fig, use_container_width=True)
