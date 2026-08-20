import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import plotly.express as px
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="NSE Institutional Quant & Execution Terminal", layout="wide", page_icon="🇮🇳")

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
        padding: 14px;
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
        n_val, d_val = float(n), float(d)
        return n_val / d_val if d_val != 0 else default
    except:
        return default

def format_inr(number):
    try:
        val = float(number)
        if val >= 10000000:
            return f"INR {val / 10000000:,.2f} Cr"
        elif val >= 100000:
            return f"INR {val / 100000:,.2f} Lk"
        else:
            return f"INR {val:,.2f}"
    except:
        return "INR 0.00"

def get_financial_item(df, keys):
    if df is None or df.empty:
        return 0.0
    for key in keys:
        if key in df.index:
            val = df.loc[key].iloc[0]
            if pd.notna(val):
                return float(val)
    return 0.0

def process_single_ticker(symbol):
    symbol = symbol.strip().upper()
    if not symbol.endswith(".NS") and not symbol.endswith(".BO") and "^" not in symbol:
        symbol = f"{symbol}.NS"
        
    headers = {'User-Agent': 'Mozilla/5.0'}
    ticker = yf.Ticker(symbol)
    
    price = 0.0
    try:
        price = ticker.fast_info.last_price
    except:
        pass
        
    if not price or pd.isna(price):
        hist = ticker.history(period="5d")
        if not hist.empty and 'Close' in hist.columns:
            price = float(hist['Close'].iloc[-1])

    info = {}
    try:
        info = ticker.info or {}
    except:
        pass

    company_name = info.get('shortName', info.get('longName', symbol.replace(".NS", "")))
    sector = info.get('sector', 'General Market')
    is_financial = any(k in sector.lower() or k in company_name.lower() for k in ['bank', 'financial', 'insurance'])

    bs = ticker.balance_sheet
    financials = ticker.financials
    cf = ticker.cashflow

    market_cap = info.get('marketCap', 0.0) or ticker.fast_info.market_cap or 0.0
    pe_ratio = info.get('trailingPE', 0.0) or 0.0
    
    # Advanced Financial Statements Parsing
    total_assets = get_financial_item(bs, ['Total Assets']) or info.get('totalAssets', 0.0)
    total_liab = get_financial_item(bs, ['Total Liabilities Net Minority Interest', 'Total Debt']) or info.get('totalDebt', 0.0)
    total_equity = get_financial_item(bs, ['Stockholders Equity', 'Total Equity Gross Minority Interest']) or info.get('totalStockholderEquity', 0.0)
    working_cap = get_financial_item(bs, ['Working Capital'])
    if working_cap == 0.0:
        ca = get_financial_item(bs, ['Current Assets'])
        cl = get_financial_item(bs, ['Current Liabilities'])
        working_cap = ca - cl

    net_income = get_financial_item(financials, ['Net Income Common Stockholders', 'Net Income']) or info.get('netIncomeToCommon', 0.0)
    revenue = get_financial_item(financials, ['Total Revenue']) or info.get('totalRevenue', 0.0)
    ebit = get_financial_item(financials, ['EBIT', 'EBITDA', 'Operating Income']) or info.get('ebitda', 0.0)
    pretax_income = get_financial_item(financials, ['Pretax Income', 'Tax Provision']) or ebit

    cfo = get_financial_item(cf, ['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities']) or info.get('operatingCashflow', 0.0)
    capex = abs(get_financial_item(cf, ['Capital Expenditure', 'Investments In Property Plant And Equipment']))
    
    # Calculate ROE %
    roe = (info.get('returnOnEquity', 0.0) or 0.0) * 100
    if roe == 0.0 and total_equity > 0:
        roe = safe_div(net_income, total_equity) * 100

    # Calculate Free Cash Flow & FCF Yield %
    if is_financial:
        fcf = cfo  # For banks, CFO acts as primary cash generator proxy
        fcf_yield = safe_div(cfo, market_cap) * 100
    else:
        fcf = info.get('freeCashflow', 0.0) or (cfo - capex)
        fcf_yield = safe_div(fcf, market_cap) * 100

    # Quantitative Models
    # 1. Emerging Market Altman Z''-Score
    retained_earnings = get_financial_item(bs, ['Retained Earnings'])
    x1 = safe_div(working_cap, total_assets)
    x2 = safe_div(retained_earnings, total_assets)
    x3 = safe_div(ebit, total_assets)
    x4 = safe_div(total_equity, total_liab)
    altman_z = (6.56 * x1) + (3.26 * x2) + (6.72 * x3) + (1.05 * x4)
    
    if is_financial:
        z_status = "N/A (Financial Firm)"
    elif altman_z > 2.60:
        z_status = "Safe Zone"
    elif altman_z >= 1.10:
        z_status = "Grey Zone"
    else:
        z_status = "Distress Zone"

    # 2. Sloan Accrual Ratio
    sloan_ratio = safe_div(net_income - cfo, total_assets) * 100
    if abs(sloan_ratio) > 15:
        sloan_status = "High Accrual Risk"
    elif abs(sloan_ratio) > 10:
        sloan_status = "Moderate Accrual"
    else:
        sloan_status = "High Cash Quality"

    # 3. Piotroski F-Score (Full 9 Criteria)
    p_score = 0
    if net_income > 0: p_score += 1
    if cfo > 0: p_score += 1
    if cfo > net_income: p_score += 1
    if roe > 8: p_score += 1
    
    total_debt = info.get('totalDebt', 0.0) or total_liab
    de_ratio = safe_div(total_debt, total_equity)
    if de_ratio < 1.5: p_score += 1
    if fcf > 0: p_score += 1
    
    op_margin = safe_div(ebit, revenue) * 100
    if op_margin > 10: p_score += 1
    
    asset_turnover = safe_div(revenue, total_assets)
    if asset_turnover > 0.4 or is_financial: p_score += 1
    if safe_div(working_cap, total_assets) > 0 or is_financial: p_score += 1

    # 4. Actionable Quant Signal Matrix (Rule-Based Decision Engine)
    quant_score = 0
    if roe > 15: quant_score += 2
    elif roe > 10: quant_score += 1
    
    if p_score >= 7: quant_score += 2
    elif p_score >= 5: quant_score += 1
    
    if fcf_yield > 3.0: quant_score += 2
    elif fcf_yield > 1.0: quant_score += 1

    if altman_z > 2.6 or is_financial: quant_score += 1
    elif altman_z < 1.1 and not is_financial: quant_score -= 2

    if sloan_status == "High Accrual Risk": quant_score -= 2

    if quant_score >= 6:
        signal = "🟢 STRONG BUY"
        action = "Accumulate on pullbacks. High fundamental strength & solid cash flow coverage."
    elif quant_score >= 4:
        signal = "🔵 ACCUMULATE"
        action = "Hold existing position or build partial size. Solid metrics with minor drag."
    elif quant_score >= 2:
        signal = "🟡 NEUTRAL"
        action = "Hold. Wait for margin expansion or earnings catalysts before adding."
    else:
        signal = "🔴 EXIT / REDUCE"
        action = "High quantitative drag. Weak cash conversion or elevated distress metrics."

    # DuPont Factors
    tax_burden = safe_div(net_income, pretax_income)
    interest_burden = safe_div(pretax_income, ebit)
    eq_multiplier = safe_div(total_assets, total_equity)

    if price > 0:
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
            "Quant Signal": signal,
            "Action Strategy": action,
            "Tax Burden": tax_burden,
            "Interest Burden": interest_burden,
            "Op Margin %": op_margin,
            "Asset Turnover": asset_turnover,
            "Equity Multiplier": eq_multiplier
        }
    return None

@st.cache_data(ttl=180)
def fetch_all_quant_data(ticker_list):
    results = []
    failed = []
    with ThreadPoolExecutor(max_workers=min(len(ticker_list), 10)) as executor:
        future_to_symbol = {executor.submit(process_single_ticker, sym): sym for sym in ticker_list}
        for future in as_completed(future_to_symbol):
            sym = future_to_symbol[future]
            try:
                res = future.result()
                if res:
                    results.append(res)
                else:
                    failed.append(sym)
            except Exception:
                failed.append(sym)
    return results, failed

# UI Layout
with st.sidebar:
    st.header("NSE / BSE Quantitative Engine")
    symbols_input = st.text_input("NSE Tickers (comma separated):", value="RELIANCE, TCS, HDFCBANK, INFY, TATAMOTORS, ICICIBANK")
    st.caption("Parallel execution engine active. Data automatically resolved across bank & non-bank balance sheets.")

st.markdown("<h1 class='hero-title'>Indian Institutional Quantitative & Execution Terminal</h1>", unsafe_allow_html=True)

ticker_list = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]

if ticker_list:
    results, failed = fetch_all_quant_data(ticker_list)
    
    if results:
        df = pd.DataFrame(results)
        
        tab_exec, tab_matrix, tab_forensics, tab_dupont, tab_visual = st.tabs([
            "🎯 Trading Signals & Execution", "📊 Master Matrix", "🔬 Forensic Audit", "🏛️ DuPont Analysis", "📈 Visual Analytics"
        ])

        with tab_exec:
            st.subheader("Actionable Quantitative Signal Matrix")
            for _, row in df.iterrows():
                with st.expander(f"{row['Quant Signal']} - {row['Company']} ({row['Symbol']}) | Live Price: INR {row['Price']:,.2f}"):
                    col1, col2, col3 = st.columns([1, 1, 2])
                    col1.metric("Quantitative Signal", row['Quant Signal'])
                    col2.metric("Piotroski / ROE", f"{row['Piotroski Score']}/9 | {row['ROE %']:.1f}%")
                    col3.info(f"**Recommended Action:** {row['Action Strategy']}")

        with tab_matrix:
            display_df = df[["Company", "Symbol", "Price", "PE", "ROE %", "FCF Yield %", "Piotroski Score", "Quant Signal"]].copy()
            display_df["Price"] = display_df["Price"].apply(lambda x: f"INR {x:,.2f}")
            display_df["ROE %"] = display_df["ROE %"].apply(lambda x: f"{x:.2f}%")
            display_df["FCF Yield %"] = display_df["FCF Yield %"].apply(lambda x: f"{x:.2f}%")
            st.dataframe(display_df, use_container_width=True)

        with tab_forensics:
            st.subheader("Forensic & Capital Allocation Audit")
            for _, row in df.iterrows():
                with st.expander(f"🔍 {row['Company']} Audit Breakdown"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Altman Z''-Score", f"{row['Altman Z-Score']:.2f}", delta=row['Z-Status'])
                    c2.metric("Sloan Accrual Ratio", f"{row['Sloan Ratio %']:.2f}%", delta=row['Sloan Status'])
                    c3.metric("FCF Yield", f"{row['FCF Yield %']:.2f}%")

        with tab_dupont:
            st.subheader("5-Step DuPont ROE Breakdown")
            selected_dupont = st.selectbox("Select Asset:", df["Symbol"].unique(), key="dupont_select")
            d_row = df[df["Symbol"] == selected_dupont].iloc[0]
            
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Op Margin %", f"{d_row['Op Margin %']:.2f}%")
            c2.metric("Asset Turnover", f"{d_row['Asset Turnover']:.2f}x")
            c3.metric("Equity Multiplier", f"{d_row['Equity Multiplier']:.2f}x")
            c4.metric("Interest Burden", f"{d_row['Interest Burden']:.2f}")
            c5.metric("Tax Burden", f"{d_row['Tax Burden']:.2f}")

        with tab_visual:
            fig = px.scatter(
                df, x="FCF Yield %", y="ROE %", size="Market Cap", 
                color="Quant Signal", hover_name="Company",
                title="FCF Yield vs Profitability (ROE %) with Signal Overlay"
            )
            fig.update_layout(template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)

    if failed:
        st.warning(f"Could not resolve quantitative data feed for: {', '.join(failed)}")
