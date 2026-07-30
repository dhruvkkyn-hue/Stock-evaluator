import streamlit as st
import pandas as pd
import sqlite3
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. ANALYTICAL HELPERS & FORMATTING
# ─────────────────────────────────────────────────────────────────────────────
def fmt(v, d=2, sfx=""):
    """Safe formatting for UI display. Handles None/NaN gracefully."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    try:
        return f"{float(v):,.{d}f}{sfx}"
    except (ValueError, TypeError):
        return "N/A"

def to_num(val):
    """Cleans Screener.in strings into floats (handles Cr, %, parentheses)."""
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
    """Extracts a row of numeric data from the 'Data Sheet' based on a label."""
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if label_query in cell_label:
            return [to_num(val) for val in df.iloc[r_idx, 1:] if to_num(val) is not None]
    return []

# ─────────────────────────────────────────────────────────────────────────────
# 2. DATA EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Target sheet 'Data Sheet' missing. Please use a standard export.")
            return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
    except Exception as e:
        st.error(f"Processing Error: {e}")
        return None

    data = {}
    data["company_name"] = str(df.iloc[0, 1]).strip()
    
    # Static & Series Data
    data["cmp"] = (get_row_series(df, "Current Price") or [None])[-1]
    data["market_cap"] = (get_row_series(df, "Market Capitalization") or [None])[-1]
    data["pe_5yr_avg"] = (get_row_series(df, "5 Year Avg PE") or [20.0])[-1]
    data["sales_series"] = get_row_series(df, "Sales")
    data["pat_series"] = get_row_series(df, "Net Profit")
    data["cfo_series"] = get_row_series(df, "Cash from Operating Activity")
    
    # Financial Components
    pat = data["pat_series"][-1] if data["pat_series"] else None
    cfo = data["cfo_series"][-1] if data["cfo_series"] else None
    eq_cap = (get_row_series(df, "Equity Share Capital") or [None])[-1]
    reserves = (get_row_series(df, "Reserves") or [None])[-1]
    borrowings = (get_row_series(df, "Borrowings") or [0.0])[-1]
    capex = (get_row_series(df, "Fixed assets purchased") or [0.0])[-1]

    # Ratio Calculations
    try:
        total_equity = (eq_cap + reserves) if (eq_cap and reserves) else None
        data["roe"] = (pat / total_equity * 100) if (total_equity and pat) else None
        data["pe"] = (data["market_cap"] / pat) if (data["market_cap"] and pat and pat > 0) else None
        data["de"] = (borrowings / total_equity) if total_equity else 0.0
        data["cfo_pat"] = (cfo / pat) if (cfo and pat and pat != 0) else None
        data["fcf"] = (cfo - abs(capex)) if cfo is not None else None
    except:
        pass

    return data

# ─────────────────────────────────────────────────────────────────────────────
# 3. STREAMLIT UI & MEMORANDUM GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Investment Analysis Terminal", layout="wide")
st.title("🏦 Master Quantitative & Business Risk Evaluator")

uploaded_file = st.file_uploader("Upload 'Data Sheet' Excel", type="xlsx")

with st.sidebar:
    st.header("Analysis Parameters")
    ticker = st.text_input("Ticker Symbol", "STOCK").upper()
    gov_ok = st.checkbox("Governance Verified (0% Pledging/Clean Audit)")
    beta_val = st.number_input("Stock Beta", value=1.1, step=0.1)

if uploaded_file:
    data = parse_file(uploaded_file)
    if data:
        # Calculate Framework Success
        s1 = (data.get("roe") or 0) >= 15
        s2 = (data.get("cfo_pat") or 0) >= 0.8
        s3 = (data.get("pe") or 100) <= (data.get("pe_5yr_avg") or 20) * 1.1
        score = sum([s1, s2, s3, gov_ok])

        # 1. DYNAMIC INVESTMENT THESIS & SUMMARY
        st.markdown("### 1. Dynamic Investment Thesis & Summary")
        
        rating = "🟢 EXCELLENT QUALITY / STRONG BUY" if score == 4 else \
                 "🟡 WATCHLIST / ACCUMULATE ON DIPS" if score == 3 else \
                 "🔴 HIGH RISK / REJECTED"
        
        with st.container():
            st.success(f"**Overall Rating: {rating}**")
            
            # Thesis Generation
            roe_txt = f"capital efficiency is robust at {fmt(data.get('roe'), 1)}% ROE" if s1 else f"capital efficiency ({fmt(data.get('roe'), 1)}%) is currently below the quality threshold"
            cash_txt = f"earnings quality is verified by high cash conversion ({fmt(data.get('cfo_pat'), 2)}x)" if s2 else "reported profits are not fully translating to cash flow, suggesting potential working capital stress"
            val_txt = f"trading at a reasonable {fmt(data.get('pe'), 1)}x P/E relative to its historical median" if s3 else f"the current P/E of {fmt(data.get('pe'), 1)}x represents a significant premium to historical norms"
            
            st.markdown(f"""
            **Core Thesis:** {data.get('company_name')} is a business where {roe_txt} and {cash_txt}. 
            From a valuation perspective, the stock is {val_txt}. 
            With a Debt-to-Equity of {fmt(data.get('de'), 2)} and a Beta of {beta_val}, the risk profile suggests a 
            {'conservative' if (data.get('de', 1) < 0.2 and beta_val < 1.0) else 'moderate to aggressive'} solvency and sensitivity posture.
            """)

        st.markdown("---")

        # 2. DETAILED STRENGTHS & WEAKNESSES
        st.markdown("### 2. Analytical Breakdown")
        col_str, col_weak = st.columns(2)
        
        with col_str:
            st.markdown("#### 🟢 Core Strengths")
            if s1: st.write(f"- **High Capital Return:** An ROE of {fmt(data.get('roe'),1)}% reflects strong pricing power and a sustainable competitive moat.")
            if s2: st.write(f"- **Cash Generation:** A CFO/PAT ratio of {fmt(data.get('cfo_pat'), 2)} verifies high earnings quality without accounting distortion.")
            if data.get("de", 1) < 0.3: st.write(f"- **Fortress Balance Sheet:** A D/E ratio of {fmt(data.get('de'), 2)} indicates minimal reliance on external debt, providing a massive solvency safety margin.")

        with col_weak:
            st.markdown("#### 🔴 Weaknesses / Key Risks")
            if not s3: st.write(f"- **Valuation Pressure:** The P/E of {fmt(data.get('pe'), 1)}x offers no margin of safety and risks multiple compression if growth slows.")
            if not s2: st.write(f"- **Earnings Quality Gap:** CFO lags PAT significantly; watch for inventory build-up or aggressive revenue recognition.")
            st.write(f"- **Growth Dependency:** Future returns are heavily dependent on maintaining the current historical revenue momentum.")

        # 3. DYNAMIC BETA & MARKET VOLATILITY ANALYSIS
        st.markdown("### 3. Market Volatility Analysis (Beta)")
        with st.expander(f"View Volatility Analysis — Current Beta: {beta_val}", expanded=True):
            if beta_val > 1.2:
                st.warning(f"**High Sensitivity ({beta_val}):** The stock is significantly more volatile than the benchmark. It amplifies gains during bull rallies but carries sharp drawdown risk during market sell-offs.")
            elif beta_val >= 0.8:
                st.info(f"**Market Synchronous ({beta_val}):** The stock moves largely in lockstep with the broader market benchmark, providing balanced market exposure.")
            else:
                st.success(f"**Defensive Asset ({beta_val}):** Low sensitivity to broader market fluctuations, providing strong downside stability during market corrections.")

        # 4. ACTIONABLE INVESTOR PLAN
        st.markdown("### 4. Actionable Investor Plan")
        p1, p2, p3 = st.columns(3)
        p1.info(f"**Step 1: Trend Check**\nVerify 3-yr & 5-yr Revenue CAGRs to confirm that the {fmt(data.get('roe'), 1)}% ROE is backed by topline expansion.")
        p2.info(f"**Step 2: Peer Assessment**\nCompare the current P/E of {fmt(data.get('pe'), 1)}x against direct sector peers to ensure you aren't overpaying for the industry cycle.")
        p3.info(f"**Step 3: Sizing Strategy**\nBased on a Beta of {beta_val}, use a {'staggered SIP entry' if beta_val > 1.0 else 'lumpsum or aggressive buy'} strategy to manage volatility.")

        # 5. HISTORICAL CONTEXT (CHARTS)
        st.markdown("---")
        with st.expander("📈 Visual Historical Context", expanded=False):
            v1, v2 = st.columns(2)
            with v1:
                if data.get("sales_series"):
                    fig1 = go.Figure()
                    fig1.add_trace(go.Scatter(y=data["sales_series"], name="Sales (Cr)", line=dict(color="#00CC96", width=3)))
                    fig1.add_trace(go.Scatter(y=data["pat_series"], name="Net Profit (Cr)", line=dict(color="#636EFA", width=3)))
                    fig1.update_layout(title="Revenue vs Profit (10Y)", template="plotly_white", height=300)
                    st.plotly_chart(fig1, use_container_width=True)
            with v2:
                if data.get("cfo_series"):
                    fig2 = go.Figure()
                    fig2.add_trace(go.Bar(y=data["pat_series"][-len(data["cfo_series"]):], name="PAT", marker_color="#636EFA"))
                    fig2.add_trace(go.Bar(y=data["cfo_series"], name="CFO", marker_color="#FFA15A"))
                    fig2.update_layout(title="PAT vs CFO (Realism)", barmode="group", template="plotly_white", height=300)
                    st.plotly_chart(fig2, use_container_width=True)
