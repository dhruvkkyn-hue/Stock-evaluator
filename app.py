import streamlit as st
import pandas as pd
import sqlite3
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. ANALYTICAL HELPERS & FORMATTING
# ─────────────────────────────────────────────────────────────────────────────
def fmt(v, d=2, sfx=""):
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

def get_row_series(df, label_query):
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if label_query in cell_label:
            return [to_num(val) for val in df.iloc[r_idx, 1:] if to_num(val) is not None]
    return []

# ─────────────────────────────────────────────────────────────────────────────
# 2. DATA EXTRACTION & VALUE ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Sheet 'Data Sheet' missing.")
            return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
    except Exception as e:
        st.error(f"Error: {e}")
        return None

    data = {}
    data["company_name"] = str(df.iloc[0, 1]).strip()
    
    # Standard Metrics
    data["cmp"] = (get_row_series(df, "Current Price") or [None])[-1]
    data["market_cap"] = (get_row_series(df, "Market Capitalization") or [None])[-1]
    data["pe_5yr_avg"] = (get_row_series(df, "5 Year Avg PE") or [20.0])[-1]
    
    # Financial Statements (Latest)
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

    # COMPUTE VALUE INVESTING METRICS
    try:
        # 1. ROIC vs WACC
        tax_rate = (tax_val / pbt) if pbt and pbt > 0 else 0.25
        nopat = op * (1 - tax_rate) if op else 0
        invested_capital = (eq_cap + reserves + borrowings - cash_val)
        data["roic"] = (nopat / invested_capital * 100) if invested_capital > 0 else None
        
        # 2. DuPont Breakdown
        data["equity"] = (eq_cap + reserves)
        data["net_margin"] = (pat / sales * 100) if sales else None
        data["asset_turnover"] = (sales / total_assets) if total_assets else None
        data["equity_multiplier"] = (total_assets / data["equity"]) if data["equity"] else None
        data["roe"] = (pat / data["equity"] * 100) if data["equity"] else None

        # 3. Compounding Runway
        net_capex = abs(capex) - depr
        data["reinvestment_rate"] = (net_capex / nopat * 100) if nopat and nopat > 0 else 0
        data["compounding_rate"] = (data["roic"] * (data["reinvestment_rate"] / 100)) if data["roic"] else None

        # 4. Owner Earnings (Buffett Metric)
        data["owner_earnings"] = (pat + depr - abs(capex))
        data["fcf"] = (cfo - abs(capex)) if cfo else None
        data["fcf_conv"] = (data["fcf"] / pat * 100) if pat and data["fcf"] else None
        
        # Ratios for Standard Dashboard
        data["de"] = (borrowings / data["equity"]) if data["equity"] else 0
        data["pe"] = (data["market_cap"] / pat) if pat and pat > 0 else None
        data["cfo_pat"] = (cfo / pat) if cfo and pat else None

    except Exception as e:
        st.error(f"Calculation Error: {e}")

    return data

# ─────────────────────────────────────────────────────────────────────────────
# 3. STREAMLIT UI - MOAT & EFFICIENCY DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Moat Analysis Terminal", layout="wide")
st.title("🏰 Economic Moat & Capital Efficiency Analysis")

uploaded_file = st.file_uploader("Upload Screener 'Data Sheet'", type="xlsx")

if uploaded_file:
    data = parse_file(uploaded_file)
    if data:
        st.header(f"🏢 {data.get('company_name')}")
        
        # Top Card Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ROIC %", fmt(data.get("roic"), 1, "%"), help="Return on Invested Capital")
        m2.metric("ROE %", fmt(data.get("roe"), 1, "%"), help="Return on Equity")
        m3.metric("Owner Earnings (Cr)", fmt(data.get("owner_earnings"), 0))
        m4.metric("D/E Ratio", fmt(data.get("de"), 2))

        # 🏰 SECTION 1: ROIC vs WACC
        st.markdown("---")
        with st.container():
            st.subheader("1. ROIC vs. WACC (Core Moat Indicator)")
            roic = data.get("roic")
            if roic is not None:
                spread = roic - 10.0 # WACC assume 10%
                if roic >= 20:
                    st.success(f"**🏰 Wide Economic Moat** — ROIC is {roic:.1f}%, generating a superior spread of {spread:.1f}% over the cost of capital.")
                elif roic >= 12:
                    st.info(f"**🛡️ Narrow Economic Moat** — ROIC is {roic:.1f}%, reflecting a moderate competitive advantage.")
                else:
                    st.error(f"**⚠️ No Moat / Value Destruction** — ROIC ({roic:.1f}%) fails to beat or barely meets the cost of capital.")
            else:
                st.write("Insufficient data to calculate ROIC.")

        # 🧬 SECTION 2: DUPONT DECOMPOSITION
        st.markdown("---")
        st.subheader("2. DuPont Decomposition of ROE")
        d1, d2, d3 = st.columns(3)
        with d1:
            st.metric("Net Profit Margin", fmt(data.get("net_margin"), 1, "%"))
            st.caption("Profitability Driver")
        with d2:
            st.metric("Asset Turnover", fmt(data.get("asset_turnover"), 2, "x"))
            st.caption("Operational Efficiency")
        with d3:
            st.metric("Equity Multiplier", fmt(data.get("equity_multiplier"), 2, "x"))
            st.caption("Financial Leverage")
        
        em = data.get("equity_multiplier", 1)
        if em and em > 2.5:
            st.warning("⚠️ **WARNING:** ROE is heavily artificially inflated by high financial leverage (debt).")
        elif data.get("net_margin", 0) > 10 and data.get("asset_turnover", 0) > 1.0:
            st.success("✅ **PURE QUALITY:** High ROE is driven by strong pricing power and asset efficiency.")

        # 🚀 SECTION 3: REINVESTMENT & COMPOUNDING
        st.markdown("---")
        st.subheader("3. Reinvestment Rate & Compounding Runway")
        r1, r2 = st.columns(2)
        re_rate = data.get("reinvestment_rate", 0)
        roic_val = data.get("roic", 0) or 0
        
        r1.metric("Reinvestment Rate", fmt(re_rate, 1, "%"))
        r2.metric("Est. Compounding Rate", fmt(data.get("compounding_rate"), 1, "%"))
        
        if roic_val > 18 and re_rate > 50:
            st.success("🚀 **Compounding Machine:** High ROIC + High Reinvestment. The business can compound capital internally at rapid rates.")
        elif roic_val > 18 and re_rate < 20:
            st.info("💰 **Cash Cow:** High ROIC but Low Reinvestment. Business generates massive surplus cash but lacks expansion runway. High Dividend/Buyback candidate.")

        # 💎 SECTION 4: OWNER EARNINGS & CONVERSION
        st.markdown("---")
        st.subheader("4. Free Cash Flow & Owner Earnings")
        f1, f2 = st.columns(2)
        fcf_conv = data.get("fcf_conv", 0)
        
        f1.metric("Owner Earnings Yield", fmt(data.get("owner_earnings")/data.get("market_cap")*100 if data.get("market_cap") else 0, 1, "%"))
        f2.metric("FCF Conversion", fmt(fcf_conv, 1, "%"))
        
        if fcf_conv >= 80:
            st.success("✅ **High Cash Conversion:** Real owner earnings match or exceed reported accounting profits.")
        elif fcf_conv < 50:
            st.error("🚩 **Poor Cash Conversion:** High capital intensity or working capital lockup detected.")

        # 5. ACTIONABLE PLAN
        st.markdown("---")
        with st.expander("📝 Actionable Investor Plan", expanded=True):
            st.write(f"1. **Check Moat Sustainability:** ROIC of {fmt(roic, 1)}% is the 'Why'. Is this due to a brand, patent, or low-cost advantage?")
            st.write(f"2. **Valuation Guardrail:** Current P/E of {fmt(data.get('pe'), 1)}x vs. the 5-Yr Avg of {fmt(data.get('pe_5yr_avg'), 1)}x. Ensure you aren't overpaying for quality.")
            st.write(f"3. **Capital Allocation:** Does management pay dividends or reinvest? Reinvestment rate is {fmt(re_rate, 1)}%.")
