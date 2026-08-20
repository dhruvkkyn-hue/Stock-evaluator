import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import plotly.express as px

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

CUSTOM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

@st.cache_data(ttl=300)
def fetch_stock_data(symbol: str):
    symbol = symbol.strip().upper()
    price = None
    company_name = symbol
    sector = "General Market"
    market_cap = 0.0
    pe_ratio = 0.0
    roe = 0.0
    de_ratio = 0.0
    fcf_yield = 0.0
    p_score = 0

    # ---------- Tier 1: yfinance ----------
    try:
        ticker = yf.Ticker(symbol)

        # Price (fast_info)
        try:
            price = getattr(ticker.fast_info, "last_price", None)
        except Exception:
            price = None

        # Fallback history price
        if not price or pd.isna(price):
            hist = ticker.history(period="5d")
            if not hist.empty and "Close" in hist.columns:
                price = float(hist["Close"].iloc[-1])

        # Fundamental info
        info = ticker.info or {}
        company_name = info.get("shortName") or info.get("longName") or symbol
        sector = info.get("sector", sector)
        pe_ratio = info.get("trailingPE", 0.0) or 0.0
        roe_raw = info.get("returnOnEquity", None)
        roe = roe_raw * 100 if isinstance(roe_raw, (int, float)) else 0.0
        market_cap = info.get("marketCap", ticker.fast_info.market_cap if hasattr(ticker.fast_info, "market_cap") else 0.0) or 0.0

        total_debt = info.get("totalDebt", 0.0) or 0.0
        total_equity = info.get("totalStockholderEquity", 0.0) or 0.0
        de_ratio = safe_div(total_debt, total_equity)

        cfo = info.get("operatingCashflow", 0.0) or 0.0
        fcf = info.get("freeCashflow", 0.0) or 0.0
        fcf_yield = safe_div(fcf, market_cap) * 100

        # Simple Piotroski‑like score
        net_income = info.get("netIncomeToCommon", 0) or 0
        if net_income > 0:
            p_score += 1
        if cfo > 0:
            p_score += 1
        if cfo > net_income:
            p_score += 1
        if roe > 10:
            p_score += 1
        if de_ratio > 0 and de_ratio < 1.0:
            p_score += 1
        if fcf > 0:
            p_score += 1
    except Exception:
        # yfinance completely failed; continue to Tier 2
        pass

    # ---------- Tier 2: Direct Yahoo REST ----------
    if not price or pd.isna(price) or price == 0.0:
        try:
            resp = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                                headers=CUSTOM_HEADERS, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                meta = data["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice")
                company_name = meta.get("shortName", company_name)
                sector = meta.get("exchangeTimezoneName", sector)
                market_cap = meta.get("marketCap", market_cap)
        except Exception:
            pass

    # ---------- Return if we have a usable price ----------
    if price and not pd.isna(price) and price > 0:
        return {
            "Company": company_name,
            "Symbol": symbol,
            "Sector": sector,
            "Market Cap": market_cap,
            "PE": pe_ratio,
            "ROE %": roe,
            "D/E": de_ratio,
            "FCF Yield %": fcf_yield,
            "Piotroski": p_score,
            "Price": float(price)
        }
    return None

with st.sidebar:
    st.header("🔍 Stock Selector")
    symbols_input = st.text_input("Enter Tickers (comma separated):", value="AAPL, MSFT, TSLA, RELIANCE.NS")
    complexity = st.radio("Analysis Complexity:", ["🌱 Beginner Investor", "📈 Intermediate Investor", "🏛️ Pro / Institutional Analyst"])

st.markdown("<h1 class='hero-title'>🏛️ Institutional Research Terminal</h1>", unsafe_allow_html=True)

ticker_list = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]
results = []
failed = {}
for sym in ticker_list:
    try:
        data = fetch_stock_data(sym)
        if data:
            results.append(data)
        else:
            failed[sym] = "Price not retrieved"
    except Exception as e:
        failed[sym] = str(e)

if results:
    df = pd.DataFrame(results)

    tab_matrix, tab_deep, tab_thesis, tab_risk, tab_visual = st.tabs([
        "📊 Master Matrix",
        "🔍 Metric Deep-Dive",
        "🏛️ Bull & Bear Thesis",
        "🛡️ Forensic Risk",
        "📈 Visuals"
    ])

    with tab_matrix:
        st.dataframe(df[["Company", "Symbol", "Price", "PE", "ROE %", "D/E", "FCF Yield %", "Piotroski"]], use_container_width=True)

    with tab_deep:
        selected_sym = st.selectbox("Select Company:", df["Symbol"].unique())
        row = df[df["Symbol"] == selected_sym].iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Live Price", f"${row['Price']:,.2f}")
        c2.metric("P/E Ratio", f"{row['PE']:.2f}" if row['PE'] else "N/A")
        c3.metric("ROE %", f"{row['ROE %']:.2f}%" if row['ROE %'] else "N/A")
        c4.metric("D/E Ratio", f"{row['D/E']:.2f}" if row['D/E'] else "N/A")

    with tab_thesis:
        for _, row in df.iterrows():
            st.subheader(f"{row['Company']} ({row['Symbol']})")
            if row["Piotroski"] >= 3 or row["ROE %"] > 12:
                st.success("Verdict: STRONG BUY / ACCUMULATE")
            else:
                st.warning("Verdict: HOLD / WATCHLIST")

    with tab_risk:
        st.subheader("🛡️ Forensic Risk Summary")
        for _, row in df.iterrows():
            st.write(f"**{row['Company']}**: Piotroski Score = {row['Piotroski']}/5")

    with tab_visual:
        fig = px.scatter(df, x="Price", y="ROE %", size="Market Cap", hover_name="Company",
                         title="Price vs Return on Equity")
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

if failed:
    with st.expander("🔎 Debug: Failed Tickers & Diagnostics"):
        for sym, msg in failed.items():
            st.write(f"**{sym}** – {msg}")
