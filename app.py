import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import plotly.express as px
from concurrent.futures import ThreadPoolExecutor, as_completed
import json

st.set_page_config(page_title="NSE Institutional Algorithmic Quant Terminal", layout="wide", page_icon="🇮🇳")

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
        
    ticker = yf.Ticker(symbol)
    
    price = 0.0
    try:
        price = ticker.fast_info.last_price
    except:
        pass
        
    if not price or pd.isna(price) or price == 0.0:
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
    is_financial = any(k in sector.lower() or k in company_name.lower() for k in ['bank', 'financial', 'insurance', 'holding'])

    bs = ticker.balance_sheet
    financials = ticker.financials
    cf = ticker.cashflow

    market_cap = info.get('marketCap', 0.0) or ticker.fast_info.market_cap or 0.0
    
    # Advanced Multi-Stage P/E Resolution Engine
    pe_ratio = info.get('trailingPE', 0.0) or info.get('forwardPE', 0.0) or 0.0
    eps = info.get('trailingEps', 0.0) or info.get('forwardEps', 0.0) or 0.0
    
    net_income = get_financial_item(financials, [
        'Net Income Common Stockholders', 'Net Income', 
        'Net Income From Continuing Operation Net Minority Interest'
    ]) or info.get('netIncomeToCommon', 0.0)
    
    shares_outstanding = info.get('sharesOutstanding', 0.0)
    if shares_outstanding == 0.0 and market_cap > 0 and price > 0:
        shares_outstanding = safe_div(market_cap, price)

    if pe_ratio == 0.0 and price > 0:
        if eps > 0:
            pe_ratio = safe_div(price, eps)
        elif net_income > 0 and shares_outstanding > 0:
            calculated_eps = safe_div(net_income, shares_outstanding)
            pe_ratio = safe_div(price, calculated_eps)
            eps = calculated_eps

    # Parse Balance Sheet & Income Statement
    total_assets = get_financial_item(bs, ['Total Assets']) or info.get('totalAssets', 0.0)
    total_liab = get_financial_item(bs, ['Total Liabilities Net Minority Interest', 'Total Debt']) or info.get('totalDebt', 0.0)
    total_equity = get_financial_item(bs, ['Stockholders Equity', 'Total Equity Gross Minority Interest']) or info.get('totalStockholderEquity', 0.0)
    working_cap = get_financial_item(bs, ['Working Capital'])
    if working_cap == 0.0:
        ca = get_financial_item(bs, ['Current Assets'])
        cl = get_financial_item(bs, ['Current Liabilities'])
        working_cap = ca - cl

    revenue = get_financial_item(financials, ['Total Revenue']) or info.get('totalRevenue', 0.0)
    ebit = get_financial_item(financials, ['EBIT', 'EBITDA', 'Operating Income']) or info.get('ebitda', 0.0)
    pretax_income = get_financial_item(financials, ['Pretax Income', 'Tax Provision']) or ebit

    cfo = get_financial_item(cf, ['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities']) or info.get('operatingCashflow', 0.0)
    capex = abs(get_financial_item(cf, ['Capital Expenditure', 'Investments In Property Plant And Equipment']))
    
    # Precision ROE Calculation
    roe = (info.get('returnOnEquity', 0.0) or 0.0) * 100
    if roe == 0.0 and total_equity > 0 and net_income != 0.0:
        roe = safe_div(net_income, total_equity) * 100

    # Precision Free Cash Flow & FCF Yield
    if is_financial:
        fcf = cfo if cfo != 0.0 else net_income
        fcf_yield = safe_div(fcf, market_cap) * 100 if market_cap > 0 else 0.0
    else:
        fcf = info.get('freeCashflow', 0.0)
        if fcf == 0.0 and cfo != 0.0:
            fcf = cfo - capex
        fcf_yield = safe_div(fcf, market_cap) * 100 if market_cap > 0 else 0.0

    # Quantitative Frameworks
    # 1. Emerging Market Altman Z''-Score
    retained_earnings = get_financial_item(bs, ['Retained Earnings'])
    x1 = safe_div(working_cap, total_assets)
    x2 = safe_div(retained_earnings, total_assets)
    x3 = safe_div(ebit, total_assets)
    x4 = safe_div(total_equity, total_liab)
    altman_z = (6.56 * x1) + (3.26 * x2) + (6.72 * x3) + (1.05 * x4)
    
    if is_financial:
        z_status = "N/A (Financial Asset)"
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

    # 3. Piotroski F-Score (9-Point Screen)
    p_score = 0
    if net_income > 0: p_score += 1
    if cfo > 0: p_score += 1
    if cfo > net_income: p_score += 1
    if roe > 10: p_score += 1
    
    total_debt = info.get('totalDebt', 0.0) or total_liab
    de_ratio = safe_div(total_debt, total_equity)
    if de_ratio < 1.5: p_score += 1
    if fcf > 0: p_score += 1
    
    op_margin = safe_div(ebit, revenue) * 100
    if op_margin > 12: p_score += 1
    
    asset_turnover = safe_div(revenue, total_assets)
    if asset_turnover > 0.4 or is_financial: p_score += 1
    if safe_div(working_cap, total_assets) > 0 or is_financial: p_score += 1

    # Algorithmic Factor Rating Engine (0 to 100 Composite Score)
    factor_score = 0
    if roe >= 18: factor_score += 25
    elif roe >= 12: factor_score += 15
    elif roe > 0: factor_score += 5

    if p_score >= 8: factor_score += 25
    elif p_score >= 6: factor_score += 18
    elif p_score >= 4: factor_score += 10

    if fcf_yield >= 4.0: factor_score += 25
    elif fcf_yield >= 2.0: factor_score += 18
    elif fcf_yield > 0: factor_score += 10

    if 0 < pe_ratio <= 25: factor_score += 25
    elif 25 < pe_ratio <= 45: factor_score += 15
    elif pe_ratio > 45: factor_score += 5

    # Signal & Execution Directive
    if factor_score >= 80:
        signal = "STRONG BUY"
        action = "ALLOCATE FULL SIZE: Exceptional return on capital, high cash conversion, & attractive valuation."
    elif factor_score >= 60:
        signal = "ACCUMULATE"
        action = "ALLOCATE PARTIAL SIZE: Strong fundamental core, monitor valuation entry points."
    elif factor_score >= 40:
        signal = "NEUTRAL"
        action = "HOLD: Mixed quantitative signals. Await earnings growth or factor improvement."
    else:
        signal = "EXIT / REDUCE"
        action = "LIQUIDATE / AVOID: High quantitative drag, low earnings quality, or valuation overload."

    # DuPont Factors
    tax_burden = safe_div(net_income, pretax_income)
    interest_burden = safe_div(pretax_income, ebit)
    eq_multiplier = safe_div(total_assets, total_equity)

    # API Payloads for Algorithmic Execution Engines
    algo_payload = {
        "ticker": symbol,
        "price_inr": price,
        "quant_score": factor_score,
        "signal": signal,
        "action": action,
        "metrics": {
            "pe_ratio": round(pe_ratio, 2),
            "roe_pct": round(roe, 2),
            "fcf_yield_pct": round(fcf_yield, 2),
            "piotroski_score": p_score,
            "altman_z": round(altman_z, 2),
            "sloan_ratio_pct": round(sloan_ratio, 2)
        }
    }

    if price > 0:
        return {
            "Company": company_name,
            "Symbol": symbol,
            "Sector": sector,
            "Market Cap": market_cap,
            "Price": float(price),
            "PE": pe_ratio,
            "EPS": eps,
            "ROE %": roe,
            "D/E": de_ratio,
            "FCF Yield %": fcf_yield,
            "Piotroski Score": p_score,
            "Altman Z-Score": altman_z,
            "Z-Status": z_status,
            "Sloan Ratio %": sloan_ratio,
            "Sloan Status": sloan_status,
            "Quant Score": factor_score,
            "Quant Signal": signal,
            "Action Strategy": action,
            "Algo Payload": json.dumps(algo_payload),
            "Tax Burden": tax_burden,
            "Interest Burden": interest_burden,
            "Op Margin %": op_margin,
            "Asset Turnover": asset_turnover,
            "Equity Multiplier": eq_multiplier
        }
    return None

@st.cache_data(ttl=120)
def fetch_all_quant_data(ticker_list):
    results = []
    failed = []
    with ThreadPoolExecutor(max_workers=min(len(ticker_list), 12)) as executor:
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
    st.header("NSE Algorithmic Execution Engine")
    symbols_input = st.text_input("NSE Tickers (comma separated):", value="RELIANCE, TCS, HDFCBANK, INFY, TATAMOTORS, ICICIBANK, LT")
    st.caption("Parallel Multi-Thread Engine active. Implied P/E & Fundamental Recovery active.")

st.markdown("<h1 class='hero-title'>Indian Institutional Quantitative & Algorithmic Terminal</h1>", unsafe_allow_html=True)

ticker_list = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]

if ticker_list:
    results, failed = fetch_all_quant_data(ticker_list)
    
    if results:
        df = pd.DataFrame(results)
        
        tab_exec, tab_matrix, tab_algo, tab_forensics, tab_dupont, tab_visual = st.tabs([
            "🎯 Signals & Execution", "📊 Master Matrix", "🤖 Algo API Payload", "🔬 Forensic Audit", "🏛️ DuPont Analysis", "📈 Visual Analytics"
        ])

        with tab_exec:
            st.subheader("Quantitative Trading Signals & Allocation Directives")
            for _, row in df.iterrows():
                sig = row['Quant Signal']
                badge = "🟢" if "BUY" in sig else ("🔵" if "ACCUMULATE" in sig else ("🟡" if "NEUTRAL" in sig else "🔴"))
                
                with st.expander(f"{badge} {sig} | {row['Company']} ({row['Symbol']}) | INR {row['Price']:,.2f} | Score: {row['Quant Score']}/100"):
                    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
                    col1.metric("Quant Factor Score", f"{row['Quant Score']}/100")
                    col2.metric("Resolved P/E", f"{row['PE']:.2f}" if row['PE'] > 0 else "N/A")
                    col3.metric("ROE % / FCF Yield", f"{row['ROE %']:.1f}% / {row['FCF Yield %']:.1f}%")
                    col4.info(f"**Execution Directive:** {row['Action Strategy']}")

        with tab_matrix:
            display_df = df[["Company", "Symbol", "Price", "PE", "EPS", "ROE %", "FCF Yield %", "Piotroski Score", "Quant Score", "Quant Signal"]].copy()
            display_df["Price"] = display_df["Price"].apply(lambda x: f"INR {x:,.2f}")
            display_df["PE"] = display_df["PE"].apply(lambda x: f"{x:.2f}" if x > 0 else "N/A")
            display_df["EPS"] = display_df["EPS"].apply(lambda x: f"INR {x:.2f}" if x != 0 else "N/A")
            display_df["ROE %"] = display_df["ROE %"].apply(lambda x: f"{x:.2f}%")
            display_df["FCF Yield %"] = display_df["FCF Yield %"].apply(lambda x: f"{x:.2f}%")
            st.dataframe(display_df, use_container_width=True)

        with tab_algo:
            st.subheader("Algorithmic Trading JSON Payloads (Auto-Execution Ready)")
            st.caption("Copy or send these structured JSON payloads directly to automated trading APIs (e.g., Zerodha Kite Connect, Upstox, Interactive Brokers).")
            for _, row in df.iterrows():
                st.markdown(f"**Payload for `{row['Symbol']}`:**")
                st.code(row['Algo Payload'], language='json')

        with tab_forensics:
            st.subheader("Forensic Accounting & Financial Health")
            for _, row in df.iterrows():
                with st.expander(f"🔍 {row['Company']} Forensic Breakdown"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Altman Z''-Score", f"{row['Altman Z-Score']:.2f}", delta=row['Z-Status'])
                    c2.metric("Sloan Accrual Ratio", f"{row['Sloan Ratio %']:.2f}%", delta=row['Sloan Status'])
                    c3.metric("Piotroski Quality Score", f"{row['Piotroski Score']}/9")

        with tab_dupont:
            st.subheader("5-Step DuPont ROE Decomposition")
            selected_dupont = st.selectbox("Select Ticker for Decomposition:", df["Symbol"].unique(), key="dupont_select")
            d_row = df[df["Symbol"] == selected_dupont].iloc[0]
            
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Operating Margin", f"{d_row['Op Margin %']:.2f}%")
            c2.metric("Asset Turnover", f"{d_row['Asset Turnover']:.2f}x")
            c3.metric("Equity Multiplier", f"{d_row['Equity Multiplier']:.2f}x")
            c4.metric("Interest Burden", f"{d_row['Interest Burden']:.2f}")
            c5.metric("Tax Burden", f"{d_row['Tax Burden']:.2f}")

        with tab_visual:
            fig = px.scatter(
                df, x="PE", y="ROE %", size="Market Cap", 
                color="Quant Signal", hover_name="Company",
                title="Valuation (P/E Ratio) vs Profitability (ROE %)"
            )
            fig.update_layout(template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)

    if failed:
        st.warning(f"Unable to fetch data for: {', '.join(failed)}")
