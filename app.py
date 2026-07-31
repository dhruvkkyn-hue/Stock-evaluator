import streamlit as st
import pandas as pd
import sqlite3
import re
import datetime
import json
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. INSTITUTIONAL PRECISION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def safe_num(val, default=0.0):
    """Safely converts any value to a float, preventing arithmetic crashes."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def div_safe(numerator, denominator):
    """Performs division with zero and None protection."""
    n = safe_num(numerator)
    d = safe_num(denominator)
    if d == 0:
        return 0.0
    return n / d

def fmt(v, d=2, sfx="", prefix=""):
    """Formatted UI output with N/A handling."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    return f"{prefix}{safe_num(v):,.{d}f}{sfx}"

def to_num(val):
    """Cleans Screener.in raw strings into valid floats."""
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
# 2. RAW DATA EXTRACTION ENGINE (DATA SHEET SCOPE)
# ─────────────────────────────────────────────────────────────────────────────

def get_row_series(df, label_query):
    """Finds row by regex/substring and returns the full numeric series."""
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if re.search(label_query, cell_label):
            return [to_num(val) for val in df.iloc[r_idx, 1:] if to_num(val) is not None]
    return []

def get_latest(df, labels):
    """Searches multiple aliases and returns the most recent numeric value."""
    if isinstance(labels, str): labels = [labels]
    for label in labels:
        series = get_row_series(df, label)
        if series: return series[-1]
    return None

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Critical Failure: 'Data Sheet' tab not found in the uploaded file.")
            return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
    except Exception as e:
        st.error(f"Excel Parsing Error: {e}")
        return None

    data = {}
    data["company_name"] = str(df.iloc[0, 1]).strip()
    
    # ── RAW LINE ITEMS ──
    sales_series = get_row_series(df, r"sales|revenue")
    pat_series   = get_row_series(df, r"net profit|profit after tax")
    cfo_series   = get_row_series(df, r"cash from operating|cfo")
    ebit_series  = get_row_series(df, r"operating profit|ebit")
    
    data["sales_series"] = sales_series
    data["pat_series"]   = pat_series
    data["cfo_series"]   = cfo_series

    # Latest Values
    sales = sales_series[-1] if sales_series else 0
    pat   = pat_series[-1] if pat_series else 0
    ebit  = ebit_series[-1] if ebit_series else 0
    cfo   = cfo_series[-1] if cfo_series else 0
    pbt   = get_latest(df, r"profit before tax|pbt")
    
    # Balance Sheet
    share_cap  = get_latest(df, r"equity share capital|share capital")
    reserves   = get_latest(df, r"reserves")
    borrowings = get_latest(df, r"borrowings|total debt") or 0.0
    other_liab = get_latest(df, r"other liabilities|other liab") or 0.0
    total_assets = get_latest(df, r"total assets")
    cash       = get_latest(df, r"cash equivalents|cash & bank|cash") or 0.0
    capex      = get_latest(df, r"fixed assets purchased|capital expenditure|capex") or 0.0
    depr       = get_latest(df, r"depreciation") or 0.0

    # Metadata
    data["cmp"] = get_latest(df, r"current price|cmp")
    data["market_cap"] = get_latest(df, r"market capitalization|market cap")
    data["pe_5yr_avg"] = get_latest(df, [r"5 year avg pe", r"median pe"]) or 20.0

    # ── PRECISION CALCULATIONS ──
    try:
        # 1. Solvency
        equity = safe_num(share_cap) + safe_num(reserves)
        data["equity"] = equity
        data["de"] = div_safe(borrowings, equity)
        
        # 2. Capital Efficiency (ROIC)
        tax_rate = div_safe((safe_num(pbt) - safe_num(pat)), pbt) if safe_num(pbt) > 0 else 0.25
        nopat = safe_num(ebit) * (1 - tax_rate)
        invested_cap = max((equity + safe_num(borrowings) - safe_num(cash)), equity)
        data["roic"] = div_safe(nopat, invested_cap) * 100
        data["roe"] = div_safe(pat, equity) * 100

        # 3. DuPont Decomposition
        data["net_margin"] = div_safe(pat, sales) * 100
        data["asset_turnover"] = div_safe(sales, total_assets if total_assets else (equity + borrowings))
        data["equity_multiplier"] = div_safe(total_assets if total_assets else (equity + borrowings), equity)

        # 4. Cash Realism & Reinvestment
        actual_capex = abs(safe_num(capex))
        data["fcf"] = safe_num(cfo) - actual_capex
        data["owner_earnings"] = safe_num(pat) + safe_num(depr) - actual_capex
        data["fcf_conv"] = div_safe(data["fcf"], pat) * 100
        data["reinv_rate"] = div_safe(actual_capex, nopat) * 100
        data["compounding_rate"] = (data["roic"] / 100) * data["reinv_rate"]
        
        # Dashboard Ratios
        data["pe"] = div_safe(data["market_cap"], pat)
        data["cfo_pat"] = div_safe(cfo, pat)

    except Exception as e:
        st.warning(f"Analytical gap detected: {e}")

    return data

# ─────────────────────────────────────────────────────────────────────────────
# 3. UI LAYOUT & ANALYTICAL WORKSTATION
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Equity Research Terminal", layout="wide", page_icon="🏦")

# Sidebar inputs
with st.sidebar:
    st.title("🏦 Research Controls")
    ticker = st.text_input("Ticker Symbol", "STOCK").upper()
    gov_ok = st.checkbox("Governance Verified (0% Pledging & Clean Audit)")
    beta_val = st.number_input("Stock Beta", value=1.1, step=0.1)
    st.divider()
    st.caption("Instructions: Upload the full Excel export from Screener.in to generate the memorandum.")

st.title("📊 Master Quantitative & Business Risk Evaluator")
up = st.file_uploader("Upload Company Export", type="xlsx")

if up:
    data = parse_file(up)
    if data:
        # ── 1. TOP METRICS BANNER ──
        st.header(f"🏢 {data.get('company_name')}")
        m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
        m1.metric("Price", fmt(data.get('cmp')))
        m2.metric("MCap (Cr)", fmt(data.get('market_cap'), 0))
        m3.metric("ROE %", fmt(data.get('roe'), 1, "%"))
        m4.metric("P/E Ratio", fmt(data.get('pe'), 1))
        m5.metric("D/E Ratio", fmt(data.get('de'), 2))
        m6.metric("CFO/PAT", fmt(data.get('cfo_pat'), 2))
        m7.metric("ROIC %", fmt(data.get('roic'), 1, "%"))

        st.divider()

        # ── 2. MASTER FRAMEWORK SCORECARD ──
        s1 = data.get("roe", 0) >= 15
        s2 = data.get("cfo_pat", 0) >= 0.8 and data.get("fcf", 0) > 0
        s3 = data.get("pe", 100) <= (data.get("pe_5yr_avg", 20) * 1.1)
        s4 = gov_ok
        score = sum([s1, s2, s3, s4])

        if score == 4:
            st.markdown("### 🏆 VERDICT: EXCELLENT QUALITY (4/4)")
            st.success("This stock clears all institutional risk and quality hurdles. APPROVED for high-conviction research.")
        elif score == 3:
            st.markdown("### 🟡 VERDICT: WATCHLIST (3/4)")
            st.warning("High quality business, but failing one critical hurdle (likely valuation or governance). Wait for a correction.")
        else:
            st.markdown("### 🔴 VERDICT: HIGH RISK / REJECTED")
            st.error("Multiple framework failures. The business model or valuation does not meet safety standards.")

        # ── 3. ECONOMIC MOAT & CAPITAL EFFICIENCY ENGINE ──
        st.subheader("🏰 Economic Moat & Capital Efficiency Engine")
        with st.expander("View Deep-Dive Capital Analysis", expanded=True):
            col_a, col_b = st.columns(2)
            
            with col_a:
                st.markdown("**ROIC vs. WACC Analysis**")
                roic = data.get("roic", 0)
                if roic >= 20:
                    st.success(f"**🏰 Wide Economic Moat**\n\nGenerates exceptional returns on capital ({roic:.1f}%) well above the 10% cost of capital. This suggests a highly protected business model with significant pricing power.")
                elif roic >= 12:
                    st.info(f"**🛡️ Narrow Economic Moat**\n\nROIC is {roic:.1f}%, reflecting a moderate competitive advantage and respectable capital returns.")
                else:
                    st.error(f"**⚠️ No Moat / Capital Destruction**\n\nReturns ({roic:.1f}%) fail to beat the cost of capital. The business is likely struggling with commoditization or high competitive intensity.")

            with col_b:
                st.markdown("**DuPont Decomposition of ROE**")
                st.write(f"- **Net Profit Margin:** {fmt(data.get('net_margin'), 1, '%')}")
                st.write(f"- **Asset Turnover:** {fmt(data.get('asset_turnover'), 2)}x")
                st.write(f"- **Equity Multiplier:** {fmt(data.get('equity_multiplier'), 2)}x")
                
                em = safe_num(data.get("equity_multiplier"))
                if em > 2.5:
                    st.warning("⚠️ **Interpretation:** ROE is significantly inflated by financial leverage. High risk of volatility during economic downturns.")
                else:
                    st.success("✅ **Interpretation:** ROE is largely quality-driven. Returns are fueled by healthy margins and asset efficiency rather than toxic debt.")

            st.divider()
            
            col_c, col_d = st.columns(2)
            with col_c:
                st.markdown("**Owner Earnings & Cash Quality**")
                st.write(f"- **Owner Earnings:** ₹{fmt(data.get('owner_earnings'), 0)} Cr")
                st.write(f"- **FCF Conversion:** {fmt(data.get('fcf_conv'), 1, '%')}")
                if data.get("fcf_conv", 0) > 80:
                    st.write("✅ Real owner earnings match or exceed reported accounting profits.")
                else:
                    st.write("🚩 Accounting profits are not fully translating to cash.")

            with col_d:
                st.markdown("**Compounding Runway**")
                reinv = data.get("reinv_rate", 0)
                st.write(f"- **Reinvestment Rate:** {fmt(reinv, 1, '%')}")
                st.write(f"- **Compounding Rate:** {fmt(data.get('compounding_rate'), 1, '%')}")
                if reinv > 50 and data.get("roic", 0) > 18:
                    st.write("🚀 **Business Type:** Compounding Engine. Can reinvest profits at very high rates.")
                elif data.get("roic", 0) > 18:
                    st.write("💰 **Business Type:** Cash Cow. Generates massive cash but lacks high-return expansion runway.")

        # ── 4. DEEP-DIVE INVESTMENT THESIS & STRATEGY ──
        st.subheader("💡 Deep-Dive Investment Thesis & Strategy")
        
        # Dynamic Thesis Generation
        thesis = f"{data.get('company_name')} presents a "
        if score >= 3:
            thesis += f"compelling quality-focused narrative. With an ROIC of {data.get('roic'):.1f}%, the business demonstrates a sustainable moat. "
        else:
            thesis += f"risk-heavy setup. The metrics indicate structural challenges in capital efficiency or valuation. "
        
        st.markdown(f"**📌 Executive Thesis:** {thesis} Earnings quality is {'robust' if s2 else 'questionable'}, while the current valuation is {'historically attractive' if s3 else 'expensive'}. Risk management should focus on the {beta_val} beta volatility.")

        col_st1, col_st2 = st.columns(2)
        with col_st1:
            st.markdown("### 🟢 Core Strengths")
            st.markdown(f"- **Exceptional Capital Efficiency:** ROE of {fmt(data.get('roe'),1)}% and ROIC of {fmt(data.get('roic'),1)}% suggest dominant market position and pricing power.")
            st.markdown(f"- **Earnings Purity:** A CFO/PAT of {fmt(data.get('cfo_pat'),2)} confirms that reported profits are backed by actual cash inflows, minimizing accounting risk.")
            st.markdown(f"- **Solvency Profile:** With a D/E of {fmt(data.get('de'),2)}, the company maintains a fortress balance sheet capable of weathering interest rate shocks.")

        with col_st2:
            st.markdown("### 🔴 Weaknesses & Analytical Risks")
            if not s3:
                st.markdown(f"- **Valuation Stretched:** P/E of {fmt(data.get('pe'),1)}x is significantly above the 5-year average ({fmt(data.get('pe_5yr_avg'),1)}x). Multiple compression is a major risk.")
            else:
                st.markdown(f"- **Historical Mean Reversion:** While currently fairly valued, any drop in ROE could trigger a swift re-rating of the stock price.")
            
            if beta_val > 1.2:
                st.markdown(f"- **Volatility Sensitivity:** A beta of {beta_val} indicates high sensitivity to market downturns. Expect sharp drawdowns if the broader index corrects.")
            
            st.markdown("- **Working Capital Cycles:** Any increase in receivables or inventory days could rapidly erode the currently healthy FCF conversion.")

        st.divider()

        # ── 5. ACTIONABLE INVESTOR PLAN ──
        st.subheader("📋 Actionable Investor Plan")
        p1, p2, p3 = st.columns(3)
        p1.info(f"**Step 1: Trend Verification**\n\nReview the 3-year Revenue CAGR. Ensure that the {fmt(data.get('roe'),1)}% ROE is being fueled by topline expansion and not just cost-cutting.")
        p2.info(f"**Step 2: Peer Benchmarking**\n\nCompare the current P/E of {fmt(data.get('pe'),1)}x against the sector leader. Determine if the quality premium is justified.")
        p3.info(f"**Step 3: Execution Strategy**\n\nGiven the Beta of {beta_val}, {'use a SIP/Staggered entry' if beta_val > 1.0 else 'a more aggressive entry can be considered'} during market dips.")

        # ── 6. CHARTS ──
        if data.get("sales_series"):
            with st.expander("📈 Historical Financial Charts"):
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data["sales_series"], name="Revenue", line=dict(color="#00CC96", width=3)))
                fig.add_trace(go.Scatter(y=data["pat_series"], name="Net Profit", line=dict(color="#636EFA", width=3)))
                fig.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=30, b=20))
                st.plotly_chart(fig, use_container_width=True)
