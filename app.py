import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(page_title="Institutional Equity Terminal", layout="wide", page_icon="💎")

st.markdown("""
<style>
    :root {
        --bg-dark: #0e1117;
        --card-bg: #161b22;
        --border-color: #30363d;
        --text-main: #c9d1d9;
        --accent-emerald: #10b981;
    }
    .stApp { background-color: var(--bg-dark); color: var(--text-main); }
    div[data-testid="stMetric"] {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 18px;
        border-radius: 10px;
    }
    .hero-title {
        font-size: 2.3rem;
        font-weight: 800;
        background: linear-gradient(90deg, #ffffff, #94a3b8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
</style>
""", unsafe_allow_html=True)

def safe_div(n, d, default=0.0):
    try:
        return float(n) / float(d) if float(d) != 0 else default
    except:
        return default

@st.cache_data(ttl=300)
def fetch_stock_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if not info or ('shortName' not in info and 'longName' not in info):
            return None
            
        financials = ticker.financials
        balance_sheet = ticker.balance_sheet
        cashflow = ticker.cashflow
        
        market_cap = info.get('marketCap', 0.0)
        pe_ratio = info.get('trailingPE', 0.0)
        roe = info.get('returnOnEquity', 0.0) * 100 if info.get('returnOnEquity') else 0.0
        
        total_debt = info.get('totalDebt', 0.0)
        total_equity = info.get('totalStockholderEquity', 0.0)
        if not total_equity and not balance_sheet.empty and 'Stockholders Equity' in balance_sheet.index:
            total_equity = balance_sheet.loc['Stockholders Equity'].iloc[0]
            
        de_ratio = safe_div(total_debt, total_equity)
        
        cfo = 0.0
        if not cashflow.empty and 'Operating Cash Flow' in cashflow.index:
            cfo = cashflow.loc['Operating Cash Flow'].iloc[0]
            
        capex = 0.0
        if not cashflow.empty and 'Capital Expenditure' in cashflow.index:
            capex = abs(cashflow.loc['Capital Expenditure'].iloc[0])
            
        fcf = cfo - capex
        fcf_yield = safe_div(fcf, market_cap) * 100
        
        sector = info.get('sector', 'Industrial')
        is_fin = 'Financial' in sector or 'Bank' in sector
        
        p_score = 0
        if info.get('netIncomeToCommon', 0) > 0: p_score += 1
        if cfo > 0: p_score += 1
        if cfo > info.get('netIncomeToCommon', 0): p_score += 1
        if roe > 10: p_score += 1
        if de_ratio < 1.0: p_score += 1
        if fcf > 0: p_score += 1
        
        return {
            "Company": info.get('shortName', info.get('longName', symbol)),
            "Symbol": symbol.upper(),
            "Sector": sector,
            "Is_Financial": is_fin,
            "Market Cap": market_cap,
            "PE": pe_ratio,
            "ROE %": roe,
            "D/E": de_ratio,
            "FCF Yield %": fcf_yield,
            "Piotroski": p_score,
            "Price": info.get('currentPrice', info.get('navPrice', 0.0))
        }
    except Exception:
        return None

with st.sidebar:
    st.header("🔍 Stock Selector")
    symbols_input = st.text_input("Enter Tickers (comma separated):", value="AAPL, MSFT, RELIANCE.NS")
    complexity = st.radio("Analysis Complexity:", ["🌱 Beginner Investor", "📈 Intermediate Investor", "🏛️ Pro / Institutional Analyst"])

st.markdown("<h1 class='hero-title'>🏛️ Institutional Research Terminal</h1>", unsafe_allow_html=True)

ticker_list = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]
results = []

for sym in ticker_list:
    data = fetch_stock_data(sym)
    if data:
        results.append(data)

if results:
    df = pd.DataFrame(results)
    
    tab_matrix, tab_deep, tab_thesis, tab_risk, tab_visual = st.tabs([
        "📊 Master Matrix", "🔍 Metric Deep-Dive", "🏛️ Bull & Bear Thesis", "🛡️ Forensic Risk", "📈 Visuals"
    ])

    with tab_matrix:
        st.dataframe(df[["Company", "Symbol", "Price", "PE", "ROE %", "D/E", "FCF Yield %", "Piotroski"]], use_container_width=True)

    with tab_deep:
        selected_sym = st.selectbox("Select Company:", df["Symbol"].unique())
        row = df[df["Symbol"] == selected_sym].iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Live Price", f"${row['Price']:,.2f}")
        c2.metric("P/E Ratio", f"{row['PE']:.2f}")
        c3.metric("ROE %", f"{row['ROE %']:.2f}%")
        c4.metric("D/E Ratio", f"{row['D/E']:.2f}")

    with tab_thesis:
        for _, row in df.iterrows():
            st.subheader(f"{row['Company']} ({row['Symbol']})")
            if row['Piotroski'] >= 4 and row['ROE %'] > 12:
                st.success("Verdict: STRONG BUY / ACCUMULATE")
            else:
                st.warning("Verdict: HOLD / WATCHLIST")

    with tab_risk:
        st.subheader("🛡️ Forensic Risk Summary")
        for _, row in df.iterrows():
            st.write(f"**{row['Company']}**: Piotroski Score = {row['Piotroski']}/6")

    with tab_visual:
        fig = px.scatter(df, x="PE", y="ROE %", size="Market Cap", hover_name="Company", title="Valuation vs Return on Equity")
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
else:
    st.error("No valid stock data found. Please verify ticker symbols.")
