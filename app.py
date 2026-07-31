import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.graph_objects as go

# ------------------------------------------------------------------------------
# 1. ANALYTICAL CONFIGURATION & MAPPING
# ------------------------------------------------------------------------------
# Fuzzy labels to match Screener.in row names
MAPPING = {
    "sales": [r"sales", r"revenue", r"turnover"],
    "exp_raw_mat": [r"raw material"],
    "exp_employee": [r"employee cost"],
    "operating_profit": [r"operating profit", r"ebitda"],
    "depreciation": [r"depreciation"],
    "interest": [r"interest"],
    "pbt": [r"profit before tax", r"pbt"],
    "tax": [r"tax"],
    "pat": [r"net profit", r"pat", r"profit after tax"],
    "equity_cap": [r"share capital"],
    "reserves": [r"reserves"],
    "borrowings": [r"borrowings", r"total debt"],
    "other_liab": [r"other liabilities"],
    "fixed_assets": [r"net block", r"fixed assets"],
    "investments": [r"investments"],
    "receivables": [r"receivables"],
    "cash": [r"cash", r"bank balance"],
    "total_assets": [r"total assets"],
    "cfo": [r"cash from operating activity", r"cfo"],
    "capex": [r"fixed assets purchased", r"capital expenditure"],
}

PLAIN_ENGLISH = {
    "roe": "How efficiently management reinvests ₹100 of shareholder money into real profit.",
    "roic": "The actual return earned on all capital (debt + equity) put into the business.",
    "cfo_pat": "The 'Truth Test' checking if reported paper profits are turning into actual bank cash.",
    "de": "How heavily the company relies on borrowed money vs its own savings.",
    "sloan": "An automated Lie Detector scanning for suspicious accounting accruals.",
    "graham": "The 'Fair Price' Benjamin Graham would pay based on current earnings and book value.",
}

# ------------------------------------------------------------------------------
# 2. DATA SANITIZATION & EXTRACTION ENGINE
# ------------------------------------------------------------------------------
def clean_numeric(val):
    """Clean symbols, commas, and formatting from Screener cells."""
    if pd.isna(val) or val == "" or val == "-":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    # Remove everything except numbers, dots, and minus signs
    cleaned = re.sub(r'[^\d\.\-]', '', str(val))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def extract_row(df, keywords):
    """Fuzzy match row labels and return cleaned numeric series."""
    for pattern in keywords:
        mask = df.iloc[:, 0].str.contains(pattern, case=False, na=False, regex=True)
        if mask.any():
            row_data = df[mask].iloc[0, 1:]
            return np.array([clean_numeric(x) for x in row_data])
    return None

# ------------------------------------------------------------------------------
# 3. FINANCIAL CALCULATION CORE
# ------------------------------------------------------------------------------
class ValueEngine:
    def __init__(self, df):
        self.df = df
        self.data = {}
        self.is_bank = False
        self.run_extraction()

    def run_extraction(self):
        # Determine if it's a Bank/NBFC
        if self.df.iloc[:, 0].str.contains("Interest Expended|Advances", case=False).any():
            self.is_bank = True

        for key, keywords in MAPPING.items():
            res = extract_row(self.df, keywords)
            self.data[key] = res if res is not None else np.zeros(10)

    def calculate_metrics(self):
        d = self.data
        # Handle zero division safety
        def safe_div(a, b): return np.divide(a, b, out=np.zeros_like(a), where=b!=0)

        results = {}
        # 1. Basic Ratios
        equity = d['equity_cap'] + d['reserves']
        results['roe'] = safe_div(d['pat'], equity) * 100
        results['de'] = safe_div(d['borrowings'], equity)
        results['cfo_pat'] = safe_div(d['cfo'], d['pat'])
        
        # 2. DuPont 5-Stage
        # Tax Burden * Interest Burden * EBIT Margin * Asset Turnover * Equity Multiplier
        ebit = d['pbt'] + d['interest']
        results['tax_burden'] = safe_div(d['pat'], d['pbt'])
        results['int_burden'] = safe_div(d['pbt'], ebit)
        results['ebit_margin'] = safe_div(ebit, d['sales'])
        results['asset_turnover'] = safe_div(d['sales'], d['total_assets'])
        results['equity_multiplier'] = safe_div(d['total_assets'], equity)
        
        # 3. Forensic: Sloan Ratio
        results['sloan'] = safe_div((d['pat'] - d['cfo']), d['total_assets'])
        
        # 4. Valuation: Graham Number
        # SQRT(22.5 * EPS * BVPS) -> Approximation using MCap and Equity
        eps_total = d['pat'] # Working with Cr directly
        bv_total = equity
        # In Screener Cr units: SQRT(22.5 * PAT_Cr * Equity_Cr) / Shares (skipped shares for simplicity)
        results['graham_value_total'] = np.sqrt(np.maximum(0, 22.5 * d['pat'] * equity))
        
        return results

# ------------------------------------------------------------------------------
# 4. STREAMLIT UI
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Principal Value Terminal", layout="wide")

st.title("🏦 Institutional Equity Research Terminal")
st.subheader("Automated 10-Year Value Investing Framework")

uploaded_file = st.file_uploader("Upload Screener.in Excel File", type="xlsx")

if uploaded_file:
    # Load raw Data Sheet
    try:
        raw_df = pd.read_excel(uploaded_file, sheet_name='Data Sheet', header=None)
        # Drop empty rows and columns
        raw_df = raw_df.dropna(how='all').dropna(axis=1, how='all')
    except Exception as e:
        st.error(f"Error reading 'Data Sheet'. Please ensure the tab exists. {e}")
        st.stop()

    engine = ValueEngine(raw_df)
    metrics = engine.calculate_metrics()
    
    # --- EXECUTIVE DASHBOARD ---
    col1, col2, col3, col4 = st.columns(4)
    latest_roe = metrics['roe'][-1]
    latest_cfo_pat = metrics['cfo_pat'][-1]
    latest_de = metrics['de'][-1]
    mcap = engine.data['market_cap'][0] # Usually in early columns

    col1.metric("10-Year ROE (Avg)", f"{np.mean(metrics['roe']):.2f}%")
    col2.metric("Cash Realism (CFO/PAT)", f"{latest_cfo_pat:.2f}x")
    col3.metric("Solvency (D/E)", f"{latest_de:.2f}")
    col4.metric("Forensic (Sloan Ratio)", f"{metrics['sloan'][-1]*100:.2f}%")

    # --- DECISION ENGINE SCORE ---
    st.divider()
    
    score = 0
    if latest_roe >= 15: score += 25
    if latest_cfo_pat >= 0.8: score += 20
    if latest_de <= 0.5: score += 20
    if metrics['sloan'][-1] < 0.1: score += 15
    # Valuation Score (Simplified logic)
    curr_mcap = engine.data['market_cap'].max()
    fair_mcap = metrics['graham_value_total'][-1]
    if curr_mcap < fair_mcap: score += 20

    score_color = "green" if score >= 70 else "orange" if score >= 50 else "red"
    st.markdown(f"## 🏆 BUFFETT/MUNGER SCORE: :{score_color}[{score} / 100]")
    
    if score >= 75: stance, color = "🟢 BUY / HIGH CONVICTION", "green"
    elif score >= 50: stance, color = "🟡 WAIT / WATCHLIST", "orange"
    else: stance, color = "🔴 AVOID / REJECTED", "red"
    
    st.subheader(f"ACTIONABLE STANCE: :{color}[{stance}]")

    # --- PLAIN ENGLISH TRANSLATION SECTION ---
    with st.expander("📝 Plain English Metric Guide", expanded=True):
        for key, desc in PLAIN_ENGLISH.items():
            st.markdown(f"**{key.upper()}:** {desc}")

    # --- DEEP DIVE TABS ---
    tab1, tab2, tab3 = st.tabs(["Forensics & DuPont", "Historical Trends", "Valuation Models"])

    with tab1:
        st.write("### 🧬 DuPont 5-Stage Breakdown")
        dupont_df = pd.DataFrame({
            "Tax Burden": metrics['tax_burden'],
            "Interest Burden": metrics['int_burden'],
            "EBIT Margin": metrics['ebit_margin'],
            "Asset Turnover": metrics['asset_turnover'],
            "Equity Multiplier": metrics['equity_multiplier']
        }).tail(5)
        st.table(dupont_df)
        st.info(f"**Insight:** {PLAIN_ENGLISH['roe']}")

    with tab2:
        st.write("### 📈 10-Year Revenue vs Profit Growth")
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=engine.data['sales'], name="Sales (Cr)"))
        fig.add_trace(go.Scatter(y=engine.data['pat'], name="Net Profit (Cr)"))
        st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.write("### 💎 Fair Value vs Market Cap")
        val_df = pd.DataFrame({
            "Metric": ["Current Market Cap", "Graham Fair Value", "Margin of Safety (%)"],
            "Value": [
                f"₹{curr_mcap:.2f} Cr", 
                f"₹{fair_mcap:.2f} Cr", 
                f"{((fair_mcap - curr_mcap)/fair_mcap)*100:.2f}%" if fair_mcap > 0 else "N/A"
            ]
        })
        st.table(val_df)

    # --- FINAL SUMMARY ---
    st.divider()
    c_str, c_risk = st.columns(2)
    with c_str:
        st.success("### 🟢 Core Strengths\n" + 
                   f"- Management generates {latest_roe:.1f}% on every rupee invested.\n" +
                   f"- Business converts {latest_cfo_pat*100:.1f}% of profit to real bank cash.")
    with c_risk:
        st.error("### 🔴 Key Risks\n" + 
                 f"- Debt levels are {latest_de:.2f}x of equity.\n" +
                 f"- Sloan Ratio of {metrics['sloan'][-1]*100:.1f}% indicates {'aggressive' if metrics['sloan'][-1] > 0.1 else 'safe'} accruals.")

else:
    st.info("👆 Please upload the 'Custom' Screener Excel file to begin analysis.")
