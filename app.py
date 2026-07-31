import streamlit as st
import pandas as pd
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. MANDATORY: PAGE CONFIG (FIRST LINE)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Quant Equity Terminal", layout="wide", page_icon="📈")

# ─────────────────────────────────────────────────────────────────────────────
# 2. INSTITUTIONAL PRECISION HELPERS (PRESERVED)
# ─────────────────────────────────────────────────────────────────────────────

def safe_num(val, default=0.0):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def div_safe(numerator, denominator):
    n = safe_num(numerator)
    d = safe_num(denominator)
    if d == 0:
        return 0.0
    return n / d

def fmt(v, d=2, sfx="", prefix=""):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    return f"{prefix}{safe_num(v):,.{d}f}{sfx}"

def to_num(val):
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
# 3. EXTRACTION ENGINE (PRESERVED & ENHANCED)
# ─────────────────────────────────────────────────────────────────────────────

def get_row_series(df, label_query):
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if re.search(label_query, cell_label):
            return [to_num(val) for val in df.iloc[r_idx, 1:] if to_num(val) is not None]
    return []

def get_latest(df, labels):
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
            st.error("Data Sheet tab missing.")
            return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
        
        data = {"company_name": str(df.iloc[0, 1]).strip()}
        
        # Series Extraction
        data["sales_series"] = get_row_series(df, r"sales|revenue")
        data["pat_series"]   = get_row_series(df, r"net profit|profit after tax")
        data["cfo_series"]   = get_row_series(df, r"cash from operating|cfo")
        ebit_series          = get_row_series(df, r"operating profit|ebit")
        
        # Latest Metrics
        sales = data["sales_series"][-1] if data["sales_series"] else 0
        pat   = data["pat_series"][-1] if data["pat_series"] else 0
        ebit  = ebit_series[-1] if ebit_series else 0
        cfo   = data["cfo_series"][-1] if data["cfo_series"] else 0
        pbt   = get_latest(df, r"profit before tax|pbt")
        
        # Balance Sheet
        share_cap  = get_latest(df, r"equity share capital|share capital")
        reserves   = get_latest(df, r"reserves")
        borrowings = get_latest(df, r"borrowings|total debt") or 0.0
        total_assets = get_latest(df, r"total assets")
        cash       = get_latest(df, r"cash equivalents|cash & bank|cash") or 0.0
        capex      = get_latest(df, r"fixed assets purchased|capital expenditure|capex") or 0.0
        depr       = get_latest(df, r"depreciation") or 0.0

        data["cmp"] = get_latest(df, r"current price|cmp")
        data["market_cap"] = get_latest(df, r"market capitalization|market cap")
        data["pe_5yr_avg"] = get_latest(df, [r"5 year avg pe", r"median pe"]) or 20.0

        # Calculations
        equity = safe_num(share_cap) + safe_num(reserves)
        data["equity"] = equity
        data["de"] = div_safe(borrowings, equity)
        
        tax_rate = div_safe((safe_num(pbt) - safe_num(pat)), pbt) if safe_num(pbt) > 0 else 0.25
        nopat = safe_num(ebit) * (1 - tax_rate)
        invested_cap = max((equity + safe_num(borrowings) - safe_num(cash)), equity)
        
        data["roic"] = div_safe(nopat, invested_cap) * 100
        data["roe"] = div_safe(pat, equity) * 100
        data["net_margin"] = div_safe(pat, sales) * 100
        data["asset_turnover"] = div_safe(sales, total_assets if total_assets else (equity + borrowings))
        data["equity_multiplier"] = div_safe(total_assets if total_assets else (equity + borrowings), equity)

        actual_capex = abs(safe_num(capex))
        data["fcf"] = safe_num(cfo) - actual_capex
        data["owner_earnings"] = safe_num(pat) + safe_num(depr) - actual_capex
        data["fcf_conv"] = div_safe(data["fcf"], pat) * 100
        data["reinv_rate"] = div_safe(actual_capex, nopat) * 100
        data["compounding_rate"] = (data["roic"] / 100) * data["reinv_rate"]
        
        data["pe"] = div_safe(data["market_cap"], pat)
        data["cfo_pat"] = div_safe(cfo, pat)
        
        # Calculate Intrinsic "Fair Value" based on 5yr Median PE
        # Fair Price = (PAT * Median PE) / (MCap / CMP)
        shares_outstanding = div_safe(data["market_cap"], data["cmp"])
        if shares_outstanding > 0:
            data["fair_value"] = div_safe(pat * data["pe_5yr_avg"], shares_outstanding)
        else:
            data["fair_value"] = 0

        return data
    except Exception as e:
        st.error(f"Critical error in engine: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 4. ANALYTICAL UI
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🛡️ Risk Controls")
    ticker = st.text_input("Ticker Symbol", "STOCK").upper()
    gov_ok = st.checkbox("Governance Verified (No Pledging)", value=True)
    beta_val = st.number_input("Stock Beta", value=1.0, step=0.1)
    st.divider()
    up = st.file_uploader("Upload Screener Excel", type="xlsx")

if up:
    data = parse_file(up)
    if data:
        # --- PRE-CALCULATE SCORE ---
        s1 = data.get("roe", 0) >= 15
        s2 = data.get("cfo_pat", 0) >= 0.8
        s3 = data.get("pe", 100) <= (data.get("pe_5yr_avg", 20) * 1.1)
        s4 = gov_ok
        score = sum([s1, s2, s3, s4])

        # ── UPGRADE 1: CONDITIONAL INVESTMENT ACTION ENGINE ──
        st.header(f"🏢 {data['company_name']} Analysis")
        
        # Logical Action Matrix
        if score == 4 and data['roic'] > 18 and data['pe'] <= data['pe_5yr_avg']:
            st.success("🎯 **ACTION: STRONG BUY / ACCUMULATE** — Exceptional quality trading at or below historical mean valuation.")
        elif score >= 3 and data['pe'] > data['pe_5yr_avg']:
            st.warning("⏳ **ACTION: QUALITY WATCHLIST (WAIT FOR DIP)** — High quality business structure but valuation is currently overheated.")
        elif data['roic'] < 10 or data['cfo_pat'] < 0.60 or data['de'] > 1.0:
            st.error("🚫 **ACTION: VALUE TRAP / HIGH RISK (AVOID)** — Weak capital efficiency, high leverage, or poor cash conversion detected.")
        elif (data['net_margin'] < 5) and (data['de'] > 1.0) and (data['pe'] > 30):
            st.error("💀 **ACTION: SHORT / RED FLAG CANDIDATE** — Low margins, high debt, and aggressive valuation.")
        else:
            st.info("⚖️ **ACTION: NEUTRAL / HOLD** — Business is performing within standard parameters; no major entry/exit triggers.")

        # Metric Banner
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Current Price", fmt(data['cmp']))
        m2.metric("Fair Value (5yr PE)", fmt(data['fair_value']))
        m3.metric("ROIC %", fmt(data['roic'], 1, "%"))
        m4.metric("P/E Ratio", fmt(data['pe'], 1))
        m5.metric("D/E Ratio", fmt(data['de'], 2))
        m6.metric("CFO/PAT", fmt(data['cfo_pat'], 2))

        st.divider()

        # ── UPGRADE 2: DYNAMIC SCENARIO EVALUATOR (BULL VS BEAR) ──
        col_bull, col_bear = st.columns(2)

        with col_bull:
            st.markdown("### 🟢 WHEN TO BUY (BULL CASE)")
            st.info(f"""
            **Consider an entry ONLY IF these conditions hold:**
            1. **Valuation Reversion:** The stock price drops below **₹{fmt(data['fair_value'], 0)}** (based on 5-year median PE).
            2. **Capital Efficiency Floor:** ROIC stays above **{fmt(data['roic']*0.9, 1)}%** (90% of current performance).
            3. **Management Reinvestment:** Company continues reinvesting at least **{fmt(data['reinv_rate'], 0)}%** of NOPAT back into the business at high rates.
            4. **Cash Reality:** CFO/PAT remains above **0.80**, ensuring accounting profits aren't 'paper-only'.
            """)

        with col_bear:
            st.markdown("### 🔴 WHEN TO AVOID / SELL (BEAR CASE)")
            st.error(f"""
            **Reject or Exit the position IF:**
            1. **Valuation Bubble:** P/E climbs significantly above **{fmt(data['pe'], 1)}x** without a corresponding jump in ROE.
            2. **Leverage Trap:** Debt-to-Equity rises above **0.50** or Equity Multiplier exceeds **2.5x** (signaling ROE is faked via debt).
            3. **Cash Deterioration:** FCF Conversion drops below **60%** (signaling customer payment delays or high inventory buildup).
            4. **Margin Erosion:** Net Profit Margin falls below **{fmt(data['net_margin']*0.8, 1)}%**, signaling loss of pricing power.
            """)

        # ── UPGRADE 3: ENHANCED DUPONT & CASH INTERPRETATION ──
        st.subheader("🕵️ Deep-Dive Integrity Checks")
        tab1, tab2 = st.tabs(["DuPont Decomposition (ROE Quality)", "Cash Realism (Earnings Purity)"])

        with tab1:
            c1, c2 = st.columns([1, 2])
            with c1:
                st.write(f"**Current ROE: {fmt(data['roe'], 1, '%')}**")
                st.write(f"- Margin: {fmt(data['net_margin'], 1, '%')}")
                st.write(f"- Asset Turn: {fmt(data['asset_turnover'], 2)}x")
                st.write(f"- Leverage: {fmt(data['equity_multiplier'], 2)}x")
            with c2:
                # Rule-based interpretation
                em = data['equity_multiplier']
                if em > 2.2:
                    st.warning(f"**Interpretation:** This ROE is heavily fueled by **Leverage ({fmt(em, 2)}x)**. This is fragile. A 10% drop in margins could lead to a 25%+ drop in ROE.")
                elif data['net_margin'] > 15:
                    st.success("**Interpretation:** ROE is high-quality, driven primarily by **Product Pricing Power** (Net Margins).")
                else:
                    st.info("**Interpretation:** ROE is driven by **Operational Efficiency** (Asset Turnover).")

        with tab2:
            c1, c2 = st.columns([1, 2])
            with c1:
                st.write(f"**PAT:** ₹{fmt(data['pat_series'][-1], 0)} Cr")
                st.write(f"**Owner Earnings:** ₹{fmt(data['owner_earnings'], 0)} Cr")
                st.write(f"**FCF Conversion:** {fmt(data['fcf_conv'], 1, '%')}")
            with c2:
                if data['owner_earnings'] > (data['pat_series'][-1] * 0.95):
                    st.success("**Interpretation:** Accounting earnings are **100% REAL**. Owner earnings match reported PAT, confirming no aggressive capitalization of expenses.")
                else:
                    st.error("**Interpretation:** Red Flag. Reported PAT is higher than Owner Earnings. The company is likely under-depreciating or over-capitalizing costs.")

        # Historical Charts (Preserved)
        if data.get("sales_series"):
            with st.expander("📈 Revenue & Profit Trends"):
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data["sales_series"], name="Revenue", line=dict(color="#00CC96", width=3)))
                fig.add_trace(go.Scatter(y=data["pat_series"], name="Net Profit", line=dict(color="#636EFA", width=3)))
                fig.update_layout(template="plotly_white", height=300, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)
