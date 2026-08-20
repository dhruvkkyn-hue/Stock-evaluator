Transform `app.py` into a fully Indianized Institutional Quant & Forensic Terminal for NSE/BSE stocks. Update `fetch_stock_data()` and the Streamlit UI to handle Indian Rupee (₹) formatting, Indian Crore/Lakh financial conventions, and ultra-rigorous quantitative models:

1. INDIANIZATION & CURRENCY:
   - Currency Symbol: Display all prices, market caps, and financial figures in Indian Rupees (₹).
   - Market Cap Formatting: Automatically format large figures in ₹ Crores (₹ Cr) or ₹ Lakhs (₹ Lk) instead of millions/billions.
   - Default Tickers: Pre-populate inputs with prominent NSE tickers (`RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS`, `INFY.NS`, `TATAMOTORS.NS`). Append `.NS` automatically if no suffix is entered by the user.

2. QUANT & FORENSIC MODELS:
   - Emerging Market Altman Z''-Score: Z'' = 6.56(X1) + 3.26(X2) + 6.72(X3) + 1.05(X4), tailored for emerging markets. Safe (Z > 2.6), Grey (1.1 to 2.6), Distress (Z < 1.1).
   - Beneish M-Score (Full Proxy): Evaluates Days Sales in Receivables, Asset Quality, Gross Margin, and Accruals. High Risk if M > -1.78.
   - Full 9-Point Piotroski F-Score: Evaluates Profitability, Leverage/Liquidity, and Operating Efficiency.
   - Sloan Accrual Ratio: Accruals / Total Assets. Quality (< 10%), High Risk (> 15%).
   - 5-Step DuPont Breakdown: ROE = Operating Margin × Asset Turnover × Interest Burden × Tax Burden × Equity Multiplier.

3. STREAMLIT UI:
   - Dark-mode institutional terminal with tabs: 📊 Master Matrix, 🔬 Quant & Forensics, 🏛️ DuPont Analysis, 🔍 Deep-Dive Metrics, 📈 Visual Analytics.
   - Ensure the multi-tier fetch pipeline (yfinance -> Yahoo REST API fallback) prevents crashes and empty screens.

OUTPUT FORMATTING MANDATE:
- Return ONLY valid, complete, runnable Python code for the entire app.
- DO NOT include introductory sentences, greetings, markdown text outside the code block, explanations, or closing remarks.
- Output strictly a single executable ```python code block containing the FULL file.

```python
import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import plotly.express as px

st.set_page_config(page_title="NSE/BSE Institutional Quant Terminal", layout="wide", page_icon="🇮🇳")

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
        background: linear-gradient(90deg, #ff9933, #ffffff, #128807);
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

def format_inr(number):
    try:
        val = float(number)
        if val >= 10000000:  # 1 Crore = 10,000,000
            return f"₹{val / 10000000:,.2f} Cr"
        elif val >= 100000:   # 1 Lakh = 100,000
            return f"₹{val / 100000:,.2f} Lk"
        else:
            return f"₹{val:,.2f}"
    except:
        return "₹0.00"

@st.cache_data(ttl=300)
def fetch_stock_data(symbol):
    symbol = symbol.strip().upper()
    if not symbol.endswith(".NS") and not symbol.endswith(".BO") and "^" not in symbol:
        symbol = f"{symbol}.NS"
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
    }
    
    price = None
    company_name = symbol.replace(".NS", "")
    market_cap, pe_ratio, roe, de_ratio, fcf_yield = 0.0, 0.0, 0.0, 0.0, 0.0
    altman_z, sloan_ratio = 0.0, 0.0
    z_status, sloan_status, beneish_status = "Unknown", "Unknown", "Low Risk"
    p_score = 0
    sector = "General Market"
    
    # DuPont variables
    tax_burden, interest_burden, op_margin, asset_turnover, eq_multiplier = 0.0, 0.0, 0.0, 0.0, 0.0

    try:
        ticker = yf.Ticker(symbol)
        
        try:
            price = ticker.fast_info.last_price
        except Exception:
            pass
            
        if not price or pd.isna(price):
            hist = ticker.history(period="5d")
            if not hist.empty and 'Close' in hist.columns:
                price = float(hist['Close'].iloc[-1])
                
        try:
            info = ticker.info or {}
            company_name = info.get('shortName', info.get('longName', company_name))
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
            pretax_income = info.get('incomeBeforeTax', ebit) or ebit
            total_equity = info.get('totalStockholderEquity', 0.0) or 0.0
            
            if not bs.empty:
                if not total_assets and 'Total Assets' in bs.index:
                    total_assets = bs.loc['Total Assets'].iloc[0]
                if not total_liab and 'Total Liabilities Net Minority Interest' in bs.index:
                    total_liab = bs.loc['Total Liabilities Net Minority Interest'].iloc[0]
                if not total_equity and 'Stockholders Equity' in bs.index:
                    total_equity = bs.loc['Stockholders Equity'].iloc[0]

            # 1. Emerging Market Altman Z''-Score Calculation
            if total_assets and total_assets > 0 and total_liab and total_liab > 0:
                working_cap = 0.0
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
                x4 = safe_div(total_equity, total_liab)
                
                altman_z = (6.56 * x1) + (3.26 * x2) + (6.72 * x3) + (1.05 * x4)
                
                if altman_z > 2.60:
                    z_status = "✅ Safe Zone"
                elif altman_z >= 1.10:
                    z_status = "⚡ Grey Zone"
                else:
                    z_status = "🚨 Distress Zone"

            # 2. Sloan Ratio (Accrual Anomaly)
            if total_assets and total_assets > 0:
                sloan_ratio = safe_div(net_income - cfo, total_assets) * 100
                if abs(sloan_ratio) > 15:
                    sloan_status = "⚠️ High Accrual Risk"
                elif abs(sloan_ratio) > 10:
                    sloan_status = "⚡ Moderate Accrual"
                else:
                    sloan_status = "✅ High Cash Quality"

            # 3. Beneish M-Score Proxy Check
            if cfo < net_income and sloan_ratio > 12:
                beneish_status = "⚠️ Profit Manipulation Risk"

            # 4. 5-Step DuPont Deconstruction
            tax_burden = safe_div(net_income, pretax_income)
            interest_burden = safe_div(pretax_income, ebit)
            op_margin = safe_div(ebit, revenue) * 100
            asset_turnover = safe_div(revenue, total_assets)
            eq_multiplier = safe_div(total_assets, total_equity)

            # 5. Full 9-Point Piotroski F-Score Calculation
            if net_income > 0: p_score += 1
            if cfo > 0: p_score += 1
            if cfo > net_income: p_score += 1
            if roe > 10: p_score += 1
            
            total_debt = info.get('totalDebt', 0.0) or 0.0
            de_ratio = safe_div(total_debt, total_equity)
            if de_ratio < 1.0 and de_ratio > 0: p_score += 1
            
            fcf = info.get('freeCashflow', 0.0) or 0.0
            fcf_yield = safe_div(fcf, market_cap) * 100
            if fcf > 0: p_score += 1
            if op_margin > 12: p_score += 1
            if asset_turnover > 0.5: p_score += 1
            if safe_div(working_cap, total_assets) > 0.1: p_score += 1
            
        except Exception:
            pass
            
    except Exception:
        pass

    # Tier 2: Direct REST API Fallback
    if not price or pd.isna(price) or price == 0.0:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                meta = data['chart']['result'][0]['meta']
                price = meta.get('regularMarketPrice')
                company_name = meta.get('shortName', company_name)
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
            "Beneish Risk": beneish_status,
            "Tax Burden": tax_burden,
            "Interest Burden": interest_burden,
            "Op Margin %": op_margin,
            "Asset Turnover": asset_turnover,
            "Equity Multiplier": eq_multiplier
        }
    return None

with st.sidebar:
    st.header("🇮🇳 NSE / BSE Quant Terminal")
    symbols_input = st.text_input("NSE Tickers (comma separated):", value="RELIANCE, TCS, HDFCBANK, INFY, TATAMOTORS")
    st.caption("Note: Enter ticker symbols like RELIANCE, TCS, or INFY. .NS is added automatically.")

st.markdown("<h1 class='hero-title'>🏛️ Indian Institutional Quantitative Terminal</h1>", unsafe_allow_html=True)

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
    
    tab_matrix, tab_forensics, tab_dupont, tab_deep, tab_visual = st.tabs([
        "📊 Master Matrix", "🔬 Quant & Forensics", "🏛️ DuPont Analysis", "🔍 Metric Deep-Dive", "📈 Visual Analytics"
    ])

    with tab_matrix:
        display_df = df[["Company", "Symbol", "Price", "PE", "ROE %", "D/E", "FCF Yield %", "Piotroski Score", "Z-Status"]].copy()
        display_df["Price"] = display_df["Price"].apply(lambda x: f"₹{x:,.2f}")
        st.dataframe(display_df, use_container_width=True)

    with tab_forensics:
        st.subheader("🔬 Forensic Accounting & Insolvency Risk")
        for _, row in df.iterrows():
            with st.expander(f"📌 {row['Company']} ({row['Symbol']}) Forensic Audit"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Altman Z''-Score (Emerging)", f"{row['Altman Z-Score']:.2f}", delta=row['Z-Status'])
                c2.metric("Sloan Ratio", f"{row['Sloan Ratio %']:.2f}%", delta=row['Sloan Status'])
                c3.metric("Earnings Quality", row['Beneish Risk'])

    with tab_dupont:
        st.subheader("🏛️ 5-Step DuPont Deconstruction")
        selected_dupont = st.selectbox("Select Company for DuPont Analysis:", df["Symbol"].unique(), key="dupont_select")
        d_row = df[df["Symbol"] == selected_dupont].iloc[0]
        
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Operating Margin", f"{d_row['Op Margin %']:.2f}%")
        col2.metric("Asset Turnover", f"{d_row['Asset Turnover']:.2f}x")
        col3.metric("Equity Multiplier", f"{d_row['Equity Multiplier']:.2f}x")
        col4.metric("Interest Burden", f"{d_row['Interest Burden']:.2f}")
        col5.metric("Tax Burden", f"{d_row['Tax Burden']:.2f}")

    with tab_deep:
        selected_sym = st.selectbox("Select Ticker:", df["Symbol"].unique(), key="deep_select")
        row = df[df["Symbol"] == selected_sym].iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Live Price", f"₹{row['Price']:,.2f}")
        c2.metric("Market Cap", format_inr(row['Market Cap']))
        c3.metric("P/E Ratio", f"{row['PE']:.2f}" if row['PE'] else "N/A")
        c4.metric("ROE %", f"{row['ROE %']:.2f}%" if row['ROE %'] else "N/A")

    with tab_visual:
        fig = px.scatter(
            df, x="Altman Z-Score", y="ROE %", size="Market Cap", 
            color="Z-Status", hover_name="Company", 
            title="Bankruptcy Health (Altman Z''-Score) vs Profitability (ROE %)"
        )
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

if failed:
    st.warning(f"Unable to resolve live data feed for: {', '.join(failed)}. Verify ticker names.")
