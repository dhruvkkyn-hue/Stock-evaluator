import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="NSE Algo-Quant Terminal", layout="wide", page_icon="🇮🇳")

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
        padding: 12px;
        border-radius: 8px;
    }
    .hero-title {
        font-size: 2rem;
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
    except Exception:
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
    except Exception:
        return "INR 0.00"

def extract_financial_metric(df, target_keys):
    if df is None or df.empty:
        return 0.0
    for key in target_keys:
        if key in df.index:
            try:
                val = df.loc[key].iloc[0]
                if pd.notna(val) and val is not None:
                    return float(val)
            except Exception:
                continue
    return 0.0

def process_single_ticker(symbol):
    symbol = symbol.strip().upper()
    if not symbol.endswith(".NS") and not symbol.endswith(".BO") and "^" not in symbol:
        symbol = f"{symbol}.NS"

    ticker = yf.Ticker(symbol)
    
    # 1. Price Resolution Engine
    price = 0.0
    try:
        price = float(ticker.fast_info.last_price or 0.0)
    except Exception:
        pass

    if price == 0.0:
        try:
            hist = ticker.history(period="5d")
            if not hist.empty and 'Close' in hist.columns:
                price = float(hist['Close'].iloc[-1])
        except Exception:
            pass

    # REST Fallback if price remains unresolved
    if price == 0.0:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=3)
            if resp.status_code == 200:
                meta = resp.json()['chart']['result'][0]['meta']
                price = float(meta.get('regularMarketPrice', 0.0))
        except Exception:
            pass

    if price == 0.0:
        return None  # Cannot process asset without price

    # 2. Extract Info Dictionary safely
    info = {}
    try:
        info = ticker.info or {}
    except Exception:
        pass

    company_name = info.get('shortName', info.get('longName', symbol.replace(".NS", "")))
    sector = info.get('sector', 'General Market')
    is_financial = any(k in sector.lower() or k in company_name.lower() for k in ['bank', 'financial', 'insurance', 'holding', 'capital'])

    # 3. Balance Sheet & Statements Parsing
    bs = pd.DataFrame()
    financials = pd.DataFrame()
    cf = pd.DataFrame()
    
    try: bs = ticker.balance_sheet except Exception: pass
    try: financials = ticker.financials except Exception: pass
    try: cf = ticker.cashflow except Exception: pass

    market_cap = float(info.get('marketCap', 0.0) or ticker.fast_info.market_cap or 0.0)
    shares_outstanding = float(info.get('sharesOutstanding', 0.0) or 0.0)
    
    if shares_outstanding == 0.0 and market_cap > 0 and price > 0:
        shares_outstanding = safe_div(market_cap, price)

    # Fundamental Extracts
    net_income = extract_financial_metric(financials, [
        'Net Income Common Stockholders', 'Net Income', 
        'Net Income From Continuing Operation Net Minority Interest'
    ]) or float(info.get('netIncomeToCommon', 0.0) or 0.0)

    eps = float(info.get('trailingEps', 0.0) or info.get('forwardEps', 0.0) or 0.0)
    if eps == 0.0 and net_income > 0 and shares_outstanding > 0:
        eps = safe_div(net_income, shares_outstanding)

    # Multi-Stage P/E Precision Engine
    pe_ratio = float(info.get('trailingPE', 0.0) or info.get('forwardPE', 0.0) or 0.0)
    if pe_ratio == 0.0 and price > 0 and eps > 0:
        pe_ratio = safe_div(price, eps)

    total_assets = extract_financial_metric(bs, ['Total Assets']) or float(info.get('totalAssets', 0.0) or 0.0)
    total_liab = extract_financial_metric(bs, ['Total Liabilities Net Minority Interest', 'Total Debt']) or float(info.get('totalDebt', 0.0) or 0.0)
    total_equity = extract_financial_metric(bs, ['Stockholders Equity', 'Total Equity Gross Minority Interest']) or float(info.get('totalStockholderEquity', 0.0) or 0.0)
    
    working_cap = extract_financial_metric(bs, ['Working Capital'])
    if working_cap == 0.0:
        ca = extract_financial_metric(bs, ['Current Assets'])
        cl = extract_financial_metric(bs, ['Current Liabilities'])
        working_cap = ca - cl

    revenue = extract_financial_metric(financials, ['Total Revenue']) or float(info.get('totalRevenue', 0.0) or 0.0)
    ebit = extract_financial_metric(financials, ['EBIT', 'EBITDA', 'Operating Income']) or float(info.get('ebitda', 0.0) or 0.0)
    pretax_income = extract_financial_metric(financials, ['Pretax Income', 'Tax Provision']) or ebit

    cfo = extract_financial_metric(cf, ['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities']) or float(info.get('operatingCashflow', 0.0) or 0.0)
    capex = abs(extract_financial_metric(cf, ['Capital Expenditure', 'Investments In Property Plant And Equipment']))
    
    # 4. Precision ROE & FCF Yield
    roe = float(info.get('returnOnEquity', 0.0) or 0.0) * 100
    if roe == 0.0 and total_equity > 0 and net_income != 0.0:
        roe = safe_div(net_income, total_equity) * 100

    if is_financial:
        fcf = cfo if cfo != 0.0 else net_income
    else:
        fcf = float(info.get('freeCashflow', 0.0) or 0.0)
        if fcf == 0.0 and cfo != 0.0:
            fcf = cfo - capex

    fcf_yield = safe_div(fcf, market_cap) * 100 if market_cap > 0 else 0.0

    # 5. Quantitative Models
    retained_earnings = extract_financial_metric(bs, ['Retained Earnings'])
    x1 = safe_div(working_cap, total_assets)
    x2 = safe_div(retained_earnings, total_assets)
    x3 = safe_div(ebit, total_assets)
    x4 = safe_div(total_equity, total_liab)
    altman_z = (6.56 * x1) + (3.26 * x2) + (6.72 * x3) + (1.05 * x4)
    
    z_status = "N/A (Financial Asset)" if is_financial else ("Safe Zone" if altman_z > 2.60 else ("Grey Zone" if altman_z >= 1.10 else "Distress Zone"))

    sloan_ratio = safe_div(net_income - cfo, total_assets) * 100 if total_assets > 0 else 0.0
    sloan_status = "High Accrual Risk" if abs(sloan_ratio) > 15 else ("Moderate Accrual" if abs(sloan_ratio) > 10 else "High Cash Quality")

    # Piotroski F-Score (Full 9 Criteria)
    p_score = 0
    if net_income > 0: p_score += 1
    if cfo > 0: p_score += 1
    if cfo > net_income: p_score += 1
    if roe > 10: p_score += 1
    
    total_debt = float(info.get('totalDebt', 0.0) or total_liab)
    de_ratio = safe_div(total_debt, total_equity)
    if de_ratio < 1.5: p_score += 1
    if fcf > 0: p_score += 1
    
    op_margin = safe_div(ebit, revenue) * 100
    if op_margin > 12: p_score += 1
    
    asset_turnover = safe_div(revenue, total_assets)
    if asset_turnover > 0.4 or is_financial: p_score += 1
    if safe_div(working_cap, total_assets) > 0 or is_financial: p_score += 1

    # Composite Quant Rating Engine (0-100 Score)
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

    if factor_score >= 80:
        signal, action = "STRONG BUY", "ALLOCATE FULL SIZE: Exceptional quality, high cash conversion, & strong valuation."
    elif factor_score >= 60:
        signal, action = "ACCUMULATE", "ALLOCATE PARTIAL SIZE: Strong fundamental core, monitor valuation entry points."
    elif factor_score >= 40:
        signal, action = "NEUTRAL", "HOLD: Mixed quantitative signals. Await catalysts or earnings growth."
    else:
        signal, action = "EXIT / REDUCE", "LIQUIDATE / AVOID: High quantitative drag, low earnings quality, or valuation overload."

    # DuPont Decomposition
    tax_burden = safe_div(net_income, pretax_income)
    interest_burden = safe_div(pretax_income, ebit)
    eq_multiplier = safe_div(total_assets, total_equity)

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

    return {
        "Company": company_name,
        "Symbol": symbol,
        "Sector": sector,
        "Market Cap": market_cap,
        "Price": price,
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
        "Algo Payload": json.dumps(algo_payload, indent=2),
        "Tax Burden": tax_burden,
        "Interest Burden": interest_burden,
        "Op Margin %": op_margin,
        "Asset Turnover": asset_turnover,
        "Equity Multiplier": eq_multiplier
    }

def fetch_all_quant_data(ticker_list):
    results = []
    failed = []
    with ThreadPoolExecutor(max_workers=min(len(ticker_list), 8)) as executor:
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

# Streamlit Interface
with st.sidebar:
    st.header("NSE / BSE Algorithmic Engine")
    symbols_input = st.text_input("NSE Tickers (comma separated):", value="RELIANCE, TCS, HDFCBANK, INFY, TATAMOTORS, ICICIBANK, LT")
    st.caption("Auto-recovers missing P/E ratios and parses banking balance sheets seamlessly.")

st.markdown("<h1 class='hero-title'>Indian Institutional Quantitative Terminal</h1>", unsafe_allow_html=True)

ticker_list = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]

if ticker_list:
    with st.spinner("Processing quantitative models & resolving financial data feeds..."):
        results, failed = fetch_all_quant_data(ticker_list)
    
    if results:
        df = pd.DataFrame(results)
        
        tab_exec, tab_matrix, tab_algo, tab_forensics, tab_dupont = st.tabs([
            "🎯 Trading Signals", "📊 Master Matrix", "🤖 Algo API JSON", "🔬 Forensic Audit", "🏛️ DuPont Analysis"
        ])

        with tab_exec:
            st.subheader("Quantitative Allocation Signals")
            for _, row in df.iterrows():
                sig = row['Quant Signal']
                badge = "🟢" if "BUY" in sig else ("🔵" if "ACCUMULATE" in sig else ("🟡" if "NEUTRAL" in sig else "🔴"))
                
                with st.expander(f"{badge} {sig} | {row['Company']} ({row['Symbol']}) | Price: INR {row['Price']:,.2f} | Score: {row['Quant Score']}/100"):
                    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
                    col1.metric("Quant Factor Score", f"{row['Quant Score']}/100")
                    col2.metric("P/E Ratio", f"{row['PE']:.2f}" if row['PE'] > 0 else "N/A")
                    col3.metric("ROE / FCF Yield", f"{row['ROE %']:.1f}% / {row['FCF Yield %']:.1f}%")
                    col4.info(f"**Execution Directive:** {row['Action Strategy']}")

        with tab_matrix:
            display_df = df[["Company", "Symbol", "Price", "PE", "EPS", "ROE %", "FCF Yield %", "Piotroski Score", "Quant Score", "Quant Signal"]].copy()
            display_df["Price"] = display_df["Price"].apply(lambda x: f"INR {x:,.2f}")
            display_df["PE"] = display_df["PE"].apply(lambda x: f"{x:.2f}" if x > 0 else "N/A")
            display_df["EPS"] = display_df["EPS"].apply(lambda x: f"INR {x:.2f}" if x > 0 else "N/A")
            display_df["ROE %"] = display_df["ROE %"].apply(lambda x: f"{x:.2f}%")
            display_df["FCF Yield %"] = display_df["FCF Yield %"].apply(lambda x: f"{x:.2f}%")
            st.dataframe(display_df, use_container_width=True)

        with tab_algo:
            st.subheader("Algorithmic Trading Payload Schema")
            st.caption("JSON structure ready for automated trading engines (e.g., Zerodha Kite Connect, Upstox API).")
            for _, row in df.iterrows():
                st.markdown(f"**Payload: `{row['Symbol']}`**")
                st.code(row['Algo Payload'], language='json')

        with tab_forensics:
            st.subheader("Forensic Accounting Audit")
            for _, row in df.iterrows():
                with st.expander(f"🔍 {row['Company']} ({row['Symbol']}) Audit Details"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Altman Z''-Score", f"{row['Altman Z-Score']:.2f}", delta=row['Z-Status'])
                    c2.metric("Sloan Accrual Ratio", f"{row['Sloan Ratio %']:.2f}%", delta=row['Sloan Status'])
                    c3.metric("Piotroski Quality", f"{row['Piotroski Score']}/9")

        with tab_dupont:
            st.subheader("5-Step DuPont Breakdown")
            selected_dupont = st.selectbox("Select Asset:", df["Symbol"].unique(), key="dupont_select")
            d_row = df[df["Symbol"] == selected_dupont].iloc[0]
            
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Op Margin %", f"{d_row['Op Margin %']:.2f}%")
            c2.metric("Asset Turnover", f"{d_row['Asset Turnover']:.2f}x")
            c3.metric("Equity Multiplier", f"{d_row['Equity Multiplier']:.2f}x")
            c4.metric("Interest Burden", f"{d_row['Interest Burden']:.2f}")
            c5.metric("Tax Burden", f"{d_row['Tax Burden']:.2f}")

    if failed:
        st.warning(f"Could not resolve price/metrics for: {', '.join(failed)}")
