import streamlit as st
import pandas as pd
import sqlite3
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. ROBUST NUMERIC HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def safe_num(val, default=0.0):
    """
    Safely converts any value to a float. 
    Returns the default if the value is None, NaN, or non-numeric.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def fmt(v, d=2, sfx=""):
    """Formatted UI output. Returns 'N/A' for None to prevent UI crashes."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    try:
        return f"{float(v):,.{d}f}{sfx}"
    except (ValueError, TypeError):
        return "N/A"

def to_num(val):
    """Parses Screener strings (e.g., '1,200 Cr', '(50)') into floats."""
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
# 2. DATA EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_row_series(df, label_query):
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if label_query in cell_label:
            return [to_num(val) for val in df.iloc[r_idx, 1:] if to_num(val) is not None]
    return []

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Sheet 'Data Sheet' missing.")
            return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
    except Exception as e:
        st.error(f"File Error: {e}")
        return None

    data = {}
    data["company_name"] = str(df.iloc[0, 1]).strip()
    
    # Raw Extraction
    data["cmp"] = (get_row_series(df, "Current Price") or [None])[-1]
    data["market_cap"] = (get_row_series(df, "Market Capitalization") or [None])[-1]
    data["pe_5yr_avg"] = (get_row_series(df, "5 Year Avg PE") or [20.0])[-1]
    
    pat = (get_row_series(df, "Net Profit") or [None])[-1]
    sales = (get_row_series(df, "Sales") or [None])[-1]
    op = (get_row_series(df, "Operating Profit") or [None])[-1]
    pbt = (get_row_series(df, "Profit before tax") or [None])[-1]
    tax_val = (get_row_series(df, "Tax") or [0])[-1]
    
    eq_cap = (get_row_series(df, "Equity Share Capital") or [0])[-1]
    reserves = (get_row_series(df, "Reserves") or [0])[-1]
    borrowings = (get_row_series(df, "Borrowings") or [0])[-1]
    cash = (get_row_series(df, "Cash & Equivalents") or get_row_series(df, "Cash & Bank"))
    cash_val = cash[-1] if cash else 0
    total_assets = (get_row_series(df, "Total Assets") or [None])[-1]
    depr = (get_row_series(df, "Depreciation") or [0])[-1]
    capex = (get_row_series(df, "Fixed assets purchased") or [0])[-1]
    cfo = (get_row_series(df, "Cash from Operating Activity") or [None])[-1]

    # COMPUTE VALUE ENGINE (With Zero Division Protection)
    try:
        # 1. Tax & NOPAT
        tax_rate = (safe_num(tax_val) / safe_num(pbt)) if safe_num(pbt) != 0 else 0.25
        data["nopat"] = safe_num(op) * (1 - tax_rate)
        
        # 2. Invested Capital & ROIC
        invested_cap = (safe_num(eq_cap) + safe_num(reserves) + safe_num(borrowings) - safe_num(cash_val))
        data["roic"] = (data["nopat"] / invested_cap * 100) if invested_cap != 0 else None
        
        # 3. DuPont Components
        data["equity"] = (safe_num(eq_cap) + safe_num(reserves))
        data["net_margin"] = (safe_num(pat) / safe_num(sales) * 100) if safe_num(sales) != 0 else None
        data["asset_turnover"] = (safe_num(sales) / safe_num(total_assets)) if safe_num(total_assets) != 0 else None
        data["equity_multiplier"] = (safe_num(total_assets) / data["equity"]) if data["equity"] != 0 else None
        data["roe"] = (safe_num(pat) / data["equity"] * 100) if data["equity"] != 0 else None

        # 4. Reinvestment
        net_capex = abs(safe_num(capex)) - safe_num(depr)
        data["reinvestment_rate"] = (net_capex / data["nopat"] * 100) if data["nopat"] != 0 else 0
        data["compounding_rate"] = (safe_num(data["roic"]) * (safe_num(data["reinvestment_rate"]) / 100))

        # 5. Owner Earnings
        data["owner_earnings"] = (safe_num(pat) + safe_num(depr) - abs(safe_num(capex)))
        data["fcf"] = (safe_num(cfo) - abs(safe_num(capex)))
        data["fcf_conv"] = (data["fcf"] / safe_num(pat) * 100) if safe_num(pat) != 0 else None
        
        # Dashboard Standard Metrics
        data["de"] = (safe_num(borrowings) / data["equity"]) if data["equity"] != 0 else 0
        data["pe"] = (safe_num(data["market_cap"]) / safe_num(pat)) if safe_num(pat) != 0 else None
        data["cfo_pat"] = (safe_num(cfo) / safe_num(pat)) if safe_num(pat) != 0 else None

    except Exception as e:
        st.warning(f"Calculation Gaps: {e}")

    return data

# ─────────────────────────────────────────────────────────────────────────────
# 3. STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Value Investor Terminal", layout="wide")
st.title("🏰 Economic Moat & Capital Efficiency Analysis")

up = st.file_uploader("Upload Screener 'Data Sheet'", type="xlsx")

if up:
    data = parse_file(up)
    if data:
        st.header(f"🏢 {data.get('company_name', 'Unknown')}")
        
        # KPI Row
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("ROIC %", fmt(data.get("roic"), 1, "%"))
        k2.metric("ROE %", fmt(data.get("roe"), 1, "%"))
        k3.metric("Owner Earnings (Cr)", fmt(data.get("owner_earnings"), 0))
        k4.metric("D/E Ratio", fmt(data.get("de"), 2))

        # --- Section 1: ROIC vs WACC ---
        st.markdown("---")
        st.subheader("1. ROIC vs. WACC (Moat Indicator)")
        roic_val = safe_num(data.get("roic"), -1.0) # -1 indicates missing/error
        if roic_val != -1.0:
            spread = roic_val - 10.0
            if roic_val >= 20:
                st.success(f"**Wide Economic Moat** — ROIC ({roic_val:.1f}%) significantly outperforms cost of capital.")
            elif roic_val >= 12:
                st.info(f"**Narrow Economic Moat** — ROIC ({roic_val:.1f}%) shows a healthy competitive advantage.")
            else:
                st.error(f"**No Moat / Value Destruction** — ROIC ({roic_val:.1f}%) is insufficient.")
        else:
            st.warning("Insufficient data for ROIC calculation.")

        # --- Section 2: DuPont Breakdown ---
        st.markdown("---")
        st.subheader("2. DuPont Decomposition")
        d1, d2, d3 = st.columns(3)
        with d1: st.metric("Net Profit Margin", fmt(data.get("net_margin"), 1, "%"))
        with d2: st.metric("Asset Turnover", fmt(data.get("asset_turnover"), 2, "x"))
        with d3: st.metric("Equity Multiplier", fmt(data.get("equity_multiplier"), 2, "x"))
        
        if safe_num(data.get("equity_multiplier")) > 2.5:
            st.warning("⚠️ **ROE Alert:** Returns are heavily inflated by financial leverage (debt).")
        elif safe_num(data.get("net_margin")) > 10 and safe_num(data.get("asset_turnover")) > 1.0:
            st.success("✅ **Pure Quality:** Returns are driven by pricing power and efficiency.")

        # --- Section 3: Reinvestment & Compounding ---
        st.markdown("---")
        st.subheader("3. Compounding Runway")
        r1, r2 = st.columns(2)
        r1.metric("Reinvestment Rate", fmt(data.get("reinvestment_rate"), 1, "%"))
        r2.metric("Compounding Rate", fmt(data.get("compounding_rate"), 1, "%"))
        
        if safe_num(data.get("roic")) > 18 and safe_num(data.get("reinvestment_rate")) > 50:
            st.success("🚀 **Compounding Machine:** Business can reinvest heavily at high rates.")
        elif safe_num(data.get("roic")) > 18 and safe_num(data.get("reinvestment_rate")) < 20:
            st.info("💰 **Cash Cow:** Strong returns but lacks reinvestment runway. High Dividend candidate.")

        # --- Section 4: Cash Conversion ---
        st.markdown("---")
        st.subheader("4. Cash Realism")
        f1, f2 = st.columns(2)
        
        # Protected division for Owner Earnings Yield metric
        mkt_cap = safe_num(data.get("market_cap"))
        oe_yield = (safe_num(data.get("owner_earnings")) / mkt_cap * 100) if mkt_cap > 0 else None
        
        f1.metric("Owner Earnings Yield", fmt(oe_yield, 1, "%"))
        f2.metric("FCF Conversion", fmt(data.get("fcf_conv"), 1, "%"))
        
        if safe_num(data.get("fcf_conv")) >= 80:
            st.success("✅ **High Quality:** Reported profits are fully backed by free cash.")
        elif safe_num(data.get("fcf_conv")) < 50:
            st.error("🚩 **Poor Conversion:** Profits are not reaching the bank. Check Capex/Working Capital.")
