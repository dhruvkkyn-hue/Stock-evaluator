import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import plotly.express as px

st.set_page_config(page_title="Institutional Quant & Forensic Terminal", layout="wide", page_icon="🏛️")

st.markdown("""
<style>
    :root {
        --bg-dark: #0e1117;
        --card-bg: #161b22;
        --border-color: #30363d;
        --text-main: #c9d1d9;
    }
    .stApp { background-color: var(--bg-dark); color: var(--text-main); }
    div[data-testid="stMetric"] {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 16px;
        border-radius: 8px;
    }
    .hero-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #ffffff, #64748b);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
</style>
""", unsafe_allow_html=True)

def safe_div(n, d, default=0.0):
    try:
        if d is None or n is None: return default
        return float(n) / float(d) if float(d) != 0 else default
    except:
        return default

@st.cache_data(ttl=300)
def fetch_stock_data(symbol):
    symbol = symbol.strip().upper()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
    }
    
    price = None
    company_name = symbol
    market_cap, pe_ratio, roe, de_ratio, fcf_yield = 0.0, 0.0, 0.0, 0.0, 0.0
    altman_z, sloan_ratio = 0.0, 0.0
    z_status, sloan_status, beneish_status = "Unknown", "Unknown", "Low Risk"
    p_score = 0
    sector = "General Market"

    try:
        ticker = yf.Ticker(symbol)
        
        # Extract Price
        try:
            price = ticker.fast_info.last_price
        except Exception:
            pass
            
        if not price or pd.isna(price):
            hist = ticker.history(period="5d")
            if not hist.empty and 'Close' in hist.columns:
                price = float(hist['Close'].iloc[-1])
                
        # Financial Data Processing
        try:
            info = ticker.info or {}
            company_name = info.get('shortName', info.get('longName', symbol))
            pe_ratio = info.get('trailingPE', 0.0) or 0.0
            roe = (info.get('returnOnEquity', 0.0) or 0.0) * 100
            market_cap = info.get('marketCap', 0.0) or ticker.fast_info.market_cap or 0.0
            sector = info.get('sector', 'General Market')
            
            bs = ticker.balance_sheet
            is_df = ticker.financials
            cf = ticker.cashflow
            
            total_assets = info.get('totalAssets', 0.0)
            total_liab = info.get('totalDebt', 0.0)
            net_income = info.get('netIncomeToCommon', 0.0) or 0.0
            cfo = info.get('operatingCashflow', 0.0) or 0.0
            ebit = info.get('ebitda', 0.0) or 0.0
            revenue = info.get('totalRevenue', 0.0) or 0.0
            
            if not bs.empty:
                if not total_assets and 'Total Assets' in bs.index:
                    total_assets = bs.loc['Total Assets'].iloc[0]
                if not total_liab and 'Total Liabilities Net Minority Interest' in bs.index:
                    total_liab = bs.loc['Total Liabilities Net Minority Interest'].iloc[0]
                    
            # 1. Sloan Ratio Calculation (Accrual Anomaly)
            if total_assets and total_assets > 0:
                sloan_ratio = safe_div(net_income - cfo, total_assets) * 100
                if abs(sloan_ratio) > 15:
                    sloan_status = "⚠️ High Accrual Risk"
                elif abs(sloan_ratio) > 10:
                    sloan_status = "⚡ Moderate Accrual"
                else:
                    sloan_status = "✅ High Cash Quality"

            # 2. Altman Z-Score Calculation (Bankruptcy Risk)
            if total_assets and total_assets > 0 and total_liab and total_liab > 0:
                working_cap = info.get('currentPrice', 0.0) # Proxy fallback
                if not bs.empty and 'Working Capital' in bs.index:
                    working_cap = bs.loc['Working Capital'].iloc[0]
                elif not bs.empty and 'Current Assets' in bs.index and 'Current Liabilities' in bs.index:
                    working_cap = bs.loc['Current Assets'].iloc[0] - bs.loc['Current Liabilities'].iloc[0]
                    
                retained_earnings = 0.0
                if not bs.empty and 'Retained Earnings' in bs.index:
                    retained_earnings = bs.loc['Retained Earnings'].iloc[0]
                    
                x1 = safe_div(working_cap, total_assets)
                x2 = safe_div(retained_earnings, total_assets)
                x3 = safe_div(ebit, total_assets)
                x4 = safe_div(market_cap, total_liab)
                x5 = safe_div(revenue, total_assets)
                
                altman_z = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (1.0 * x5)
                
                if altman_z > 2.99:
                    z_status = "✅ Safe Zone"
                elif altman_z >= 1.81:
                    z_status = "⚡ Grey Zone"
                else:
                    z_status = "🚨 Distress Zone"

            # 3. Beneish M-Score Proxy Check
            if cfo < net_income and sloan_ratio > 12:
                beneish_status = "⚠️ Profit Manipulation Risk"

            # Leverage & FCF
            total_debt = info.get('totalDebt', 0.0) or 0.0
            total_equity = info.get('totalStockholderEquity', 0.0) or 0.0
            de_ratio = safe_div(total_debt, total_equity)
            fcf = info.get('freeCashflow', 0.0) or 0.0
            fcf_yield = safe_div(fcf, market_cap) * 100

            # Piotroski F-Score Calculation
            if net_income > 0: p_score += 1
            if cfo > 0: p_score += 1
            if cfo > net_income: p_score += 1
            if roe > 10: p_score += 1
            if de_ratio < 1.0 and de_ratio > 0: p_score += 1
            if fcf > 0: p_score += 1
            
        except Exception:
            pass
            
    except Exception:
        pass

    # Tier 2: Direct REST API Fallback
    if not price or pd.isna(price) or price == 0.0:
        try:
            url = f"[https://query1.finance.yahoo.com/v8/finance/chart/](https://query1.finance.yahoo.com/v8/finance/chart/){symbol}"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                meta = data['chart']['result'][0]['meta']
                price = meta.get('regularMarketPrice')
                company_name = meta.get('shortName', symbol)
                market_cap = meta.get('marketCap', 0.0)
        except Exception:
            pass

    if price and not pd.isna(price) and price > 0:
        return {
            "Company": company_name,
            "Symbol": symbol,
            "Sector": sector,
            "Market Cap": market_cap,
            "Price": float(price),
            "PE": pe_ratio,
            "ROE %": roe,
            "D/E": de_ratio,
            "FCF Yield %": fcf_yield,
            "Piotroski Score": p_score,
            "Altman Z-Score": altman_z,
            "Z-Status": z_status,
            "Sloan Ratio %": sloan_ratio,
            "Sloan Status": sloan_status,
            "Beneish Risk": beneish_status
        }
    return None

with st.sidebar:
    st.header("⚙️ Quantitative Selector")
    symbols_input = st.text_input("Tickers (comma separated):", value="AAPL, MSFT, TSLA, RELIANCE.NS")
    st.caption("Supports US (AAPL) & International (RELIANCE.NS) stocks.")

st.markdown("<h1 class='hero-title'>🏛️ Institutional Research & Quant Terminal</h1>", unsafe_allow_html=True)

ticker_list = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]
results = []
failed = []

for sym in ticker_list:
    data = fetch_stock_data(sym)
    if data:
        results.append(data)
    else:
        failed.append(sym)

if results:
    df = pd.DataFrame(results)
    
    tab_matrix, tab_forensics, tab_deep, tab_visual = st.tabs([
        "📊 Master Matrix", "🔬 Quant & Forensics", "🔍 Deep-Dive Metrics", "📈 Visual Analytics"
    ])

    with tab_matrix:
        st.dataframe(
            df[["Company", "Symbol", "Price", "PE", "ROE %", "D/E", "FCF Yield %", "Piotroski Score", "Z-Status"]], 
            use_container_width=True
        )

    with tab_forensics:
        st.subheader("🔬 Forensic Accounting & Insolvency Risk")
        for _, row in df.iterrows():
            with st.expander(f"📌 {row['Company']} ({row['Symbol']}) Forensic Audit"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Altman Z-Score", f"{row['Altman Z-Score']:.2f}", delta=row['Z-Status'])
                c2.metric("Sloan Ratio", f"{row['Sloan Ratio %']:.2f}%", delta=row['Sloan Status'])
                c3.metric("Earnings Quality", row['Beneish Risk'])

    with tab_deep:
        selected_sym = st.selectbox("Select Ticker:", df["Symbol"].unique())
        row = df[df["Symbol"] == selected_sym].iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Live Price", f"${row['Price']:,.2f}")
        c2.metric("P/E Ratio", f"{row['PE']:.2f}" if row['PE'] else "N/A")
        c3.metric("ROE %", f"{row['ROE %']:.2f}%" if row['ROE %'] else "N/A")
        c4.metric("D/E Ratio", f"{row['D/E']:.2f}" if row['D/E'] else "N/A")

    with tab_visual:
        fig = px.scatter(
            df, x="Altman Z-Score", y="ROE %", size="Market Cap", 
            color="Z-Status", hover_name="Company", 
            title="Bankruptcy Health (Altman Z) vs Profitability (ROE)"
        )
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

if failed:
    st.warning(f"Unable to resolve live data feed for: {', '.join(failed)}. Check ticker notation.")
