import streamlit as st
import pandas as pd
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. MANDATORY: PAGE CONFIG (MUST BE FIRST)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Institutional Equity Terminal", 
    layout="wide", 
    page_icon="💎"
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. BASELINE PRECISION HELPERS (PRESERVED)
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
# 3. EXTRACTION ENGINE (PRESERVED & WRAPPED)
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
            st.error("Critical Failure: 'Data Sheet' tab not found.")
            return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
        
        data = {"company_name": str(df.iloc[0, 1]).strip()}
        
        # Core Extraction
        data["sales_series"] = get_row_series(df, r"sales|revenue")
        data["pat_series"]   = get_row_series(df, r"net profit|profit after tax")
        data["cfo_series"]   = get_row_series(df, r"cash from operating|cfo")
        ebit_series          = get_row_series(df, r"operating profit|ebit")
        
        sales = data["sales_series"][-1] if data["sales_series"] else 0
        pat   = data["pat_series"][-1] if data["pat_series"] else 0
        ebit  = ebit_series[-1] if ebit_series else 0
        cfo   = data["cfo_series"][-1] if data["cfo_series"] else 0
        pbt   = get_latest(df, r"profit before tax|pbt")
        
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

        return data
    except Exception as e:
        st.error(f"Excel Parsing Error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 4. INVESTOR INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔐 Analyst Controls")
    ticker = st.text_input("Ticker Symbol", "STOCK").upper()
    gov_ok = st.checkbox("Governance Verified", value=True, help="Tick if audit is clean and pledging is 0%.")
    beta_val = st.number_input("Stock Beta", value=1.0, step=0.1)
    st.divider()
    up = st.file_uploader("Upload Screener.in Excel", type="xlsx")

if not up:
    st.title("🏛️ Strategic Equity Evaluator")
    st.info("Please upload a Screener.in Excel export to begin high-conviction analysis.")
else:
    data = parse_file(up)
    if data:
        # --- TOP LEVEL IDENTIFICATION ---
        st.header(f"💎 {data['company_name']} | Strategic Evaluation")
        
        # ── 1. INVESTOR PROFILE MATCH ENGINE ──
        st.subheader("🎯 Investor Mandate Suitability")
        
        m_col1, m_col2 = st.columns(2)
        
        with m_col1:
            st.markdown("### 🟢 BUY IF YOUR MANDATE IS:")
            if data['roic'] > 18 and data['de'] < 0.5:
                st.success(f"**Long-Term Quality Compounder:** You seek an ROIC of {fmt(data['roic'],1)}% with low financial risk (D/E: {fmt(data['de'])}).")
            if data['fcf_conv'] > 80:
                st.success(f"**Cash Flow Purity:** You require reported profits to be backed by actual bank balance ({fmt(data['fcf_conv'],1)}% FCF Conversion).")
            if data['compounding_rate'] > 15:
                st.success(f"**Growth Reinvestment:** You back companies that aggressively reinvest ({fmt(data['reinv_rate'],0)}%) to fuel future value.")
            if data['pe'] < data['pe_5yr_avg']:
                st.success(f"**Value with Catalyst:** You want to buy quality at a discount to historical norms (Current {fmt(data['pe'],1)}x vs 5Yr Avg {fmt(data['pe_5yr_avg'],1)}x).")

        with m_col2:
            st.markdown("### 🔴 AVOID / SELL IF YOUR MANDATE IS:")
            if data['pe'] > (data['pe_5yr_avg'] * 1.25):
                st.error(f"**Margin of Safety Priority:** Current P/E ({fmt(data['pe'],1)}x) offers zero protection against multiple contraction.")
            if data['reinv_rate'] > 70:
                st.error(f"**High Dividend Yield:** This company prioritizes internal growth ({fmt(data['reinv_rate'],0)}% reinvested) over dividend payouts.")
            if beta_val > 1.3:
                st.error(f"**Low Volatility Mandate:** The stock beta of {beta_val} suggests sharp price swings that exceed your risk appetite.")
            if data['owner_earnings'] < (data['pat_series'][-1] * 0.8):
                st.error(f"**Zero Accounting Risk:** Owner Earnings lag reported profits significantly. High maintenance capex is eating the 'paper profit'.")

        st.divider()

        # ── 2. PLAIN-ENGLISH METRIC WORKSPACE ──
        st.subheader("📊 Fundamental Health & Intuitive Translations")
        
        def metric_card(title, value, translation, status="info"):
            container = st.container(border=True)
            if status == "success": color = "green"
            elif status == "warning": color = "orange"
            elif status == "error": color = "red"
            else: color = "blue"
            
            container.markdown(f"**{title}**")
            container.subheader(value)
            container.caption(f"💡 {translation}")

        # Metrics Grid
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            metric_card("ROIC", fmt(data['roic'], 1, "%"), 
                        "The actual return generated on every ₹100 of capital deployed.",
                        "success" if data['roic'] > 15 else "warning")
            metric_card("Net Margin", fmt(data['net_margin'], 1, "%"),
                        "Profit kept after all expenses. Pricing power indicator.",
                        "success" if data['net_margin'] > 12 else "info")
            
        with c2:
            metric_card("CFO/PAT", fmt(data['cfo_pat'], 2),
                        "Cash Reality Check. > 1.0 means cash is coming in faster than accounting records it.",
                        "success" if data['cfo_pat'] >= 0.8 else "error")
            metric_card("Asset Turnover", fmt(data['asset_turnover'], 2) + "x",
                        "Efficiency: How many ₹ of sales are generated by ₹1 of assets.",
                        "info")

        with c3:
            metric_card("Equity Multiplier", fmt(data['equity_multiplier'], 2) + "x",
                        "Leverage Dosage. > 2.2x indicates heavy reliance on debt to boost returns.",
                        "warning" if data['equity_multiplier'] > 2.2 else "success")
            metric_card("Owner Earnings", "₹" + fmt(data['owner_earnings'], 0) + " Cr",
                        "Spendable cash left for shareholders after essential business upkeep.",
                        "info")

        with c4:
            metric_card("Reinv. Rate", fmt(data['reinv_rate'], 1, "%"),
                        "Growth Fuel: % of cash plowed back into the business for expansion.",
                        "success" if data['reinv_rate'] > 40 else "info")
            metric_card("D/E Ratio", fmt(data['de'], 2),
                        "Solvency: ₹ of debt for every ₹1 of shareholder equity.",
                        "success" if data['de'] < 0.5 else "error")

        # ── 3. ENHANCED DUPONT DECOMPOSITION ──
        st.divider()
        st.subheader("🔬 ROE Engineering (DuPont Analysis)")
        
        # Calculate relative weights for the plain-english breakdown
        # Logarithmic breakdown or simple relative magnitude for "Drivers"
        total_driver = data['net_margin'] + (data['asset_turnover']*10) + (data['equity_multiplier']*5)
        margin_contrib = (data['net_margin'] / total_driver) * 100
        efficiency_contrib = ((data['asset_turnover']*10) / total_driver) * 100
        leverage_contrib = ((data['equity_multiplier']*5) / total_driver) * 100

        st.markdown(f"### Current ROE: **{fmt(data['roe'], 1, '%')}**")
        
        if data['equity_multiplier'] > 2.2:
            st.error(f"⚠️ **RED FLAG:** ROE of {fmt(data['roe'], 1, '%')} is artificially inflated by high leverage ({fmt(data['equity_multiplier'], 2)}x). This is not operational strength; it is balance sheet risk.")
        else:
            st.success(f"✅ **QUALITY SIGN:** ROE is largely driven by margins and efficiency, not toxic levels of debt.")

        dup1, dup2, dup3 = st.columns(3)
        dup1.metric("1. Profit Margin", fmt(data['net_margin'], 1, "%"), help="Operational Prowess")
        dup2.metric("2. Asset Efficiency", fmt(data['asset_turnover'], 2) + "x", help="Asset Utilization")
        dup3.metric("3. Leverage Factor", fmt(data['equity_multiplier'], 2) + "x", help="Financial Gearing")
        
        st.info(f"**Plain-English Breakdown:** Your {fmt(data['roe'],1)}% ROE is sourced approximately **{margin_contrib:.0f}% from Profit Margins**, **{efficiency_contrib:.0f}% from Asset Utilization**, and **{leverage_contrib:.0f}% from Financial Debt.**")

        # ── 4. VISUALIZATION ──
        st.divider()
        with st.expander("📈 View Revenue vs. Profit Trajectory"):
            if data["sales_series"]:
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data["sales_series"], name="Top-Line (Sales)", line=dict(color="#2ECC71", width=4)))
                fig.add_trace(go.Scatter(y=data["pat_series"], name="Bottom-Line (Profit)", line=dict(color="#3498DB", width=4)))
                fig.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig, use_container_width=True)

        # ── 5. FINAL DECISION SCORECARD ──
        s1 = data.get("roe", 0) >= 15
        s2 = data.get("cfo_pat", 0) >= 0.8
        s3 = data.get("pe", 100) <= (data.get("pe_5yr_avg", 20) * 1.1)
        s4 = gov_ok
        score = sum([s1, s2, s3, s4])

        st.divider()
        col_res1, col_res2 = st.columns([1, 3])
        with col_res1:
            st.header(f"Score: {score}/4")
        with col_res2:
            if score == 4:
                st.balloons()
                st.success("**INSTITUTIONAL GRADE:** This stock clears every hurdle for quality, cash, and valuation. High conviction candidate.")
            elif score == 3:
                st.warning("**WATCHLIST GRADE:** High quality business, but either the price is too high or there is a minor governance/cash flow lag.")
            else:
                st.error("**SPECULATIVE / REJECT:** Multiple fundamental failures. Does not meet the 'Safety First' criteria for long-term compounding.")

