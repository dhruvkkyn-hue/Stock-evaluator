import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ==========================================
# PAGE CONFIGURATION & STYLING
# ==========================================
st.set_page_config(page_title="NSE Standalone Quant Engine", layout="wide", page_icon="📈")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #c9d1d9; }
    div[data-testid="stMetric"] {
        background-color: #161b22;
        border: 1px solid #30363d;
        padding: 12px;
        border-radius: 8px;
    }
    .hero-title {
        font-size: 1.8rem;
        font-weight: 800;
        color: #ff9933;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# IN-MEMORY PAPER LEDGER (NO DATABASE/API REQ)
# ==========================================
if "cash_balance" not in st.session_state:
    st.session_state.cash_balance = 1000000.0  # ₹10,000,00 Virtual Capital
if "portfolio" not in st.session_state:
    st.session_state.portfolio = {}  # {symbol: {qty, avg_price, sl, target}}
if "trade_log" not in st.session_state:
    st.session_state.trade_log = []

# ==========================================
# MARKET DATA & QUANT ALGORITHM ENGINE
# ==========================================
def safe_div(n, d, default=0.0):
    try:
        if d is None or n is None: return default
        n_val, d_val = float(n), float(d)
        return n_val / d_val if d_val != 0 else default
    except Exception:
        return default

def process_ticker(symbol):
    sym_clean = symbol.strip().upper()
    ticker_sym = sym_clean if sym_clean.endswith(".NS") or sym_clean.endswith(".BO") else f"{sym_clean}.NS"
    ticker = yf.Ticker(ticker_sym)

    price = 0.0
    try:
        price = float(ticker.fast_info.last_price or 0.0)
    except Exception:
        pass

    if price == 0.0:
        try:
            hist = ticker.history(period="5d")
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])
        except Exception:
            pass

    if price == 0.0:
        return None

    info = {}
    try:
        info = ticker.info or {}
    except Exception:
        pass

    company_name = info.get('shortName', sym_clean)
    market_cap = float(info.get('marketCap', 0.0) or ticker.fast_info.market_cap or 0.0)
    
    eps = float(info.get('trailingEps', 0.0) or info.get('forwardEps', 0.0) or 0.0)
    pe_ratio = float(info.get('trailingPE', 0.0) or info.get('forwardPE', 0.0) or 0.0)
    if pe_ratio == 0 and price > 0 and eps > 0:
        pe_ratio = safe_div(price, eps)

    roe = float(info.get('returnOnEquity', 0.0) or 0.0) * 100

    # QUANTITATIVE SCORING ALGORITHM (0 - 100 Points)
    score = 0
    if 0 < pe_ratio <= 25: score += 40
    elif 25 < pe_ratio <= 40: score += 20

    if roe >= 18: score += 40
    elif roe >= 12: score += 25
    elif roe > 0: score += 10

    if market_cap > 50000000000:  # Large Cap (>5,000 Cr) Stability Bonus
        score += 20

    if score >= 60:
        signal = "BUY"
    elif score <= 30:
        signal = "SELL"
    else:
        signal = "HOLD"

    return {
        "Company": company_name,
        "Symbol": sym_clean,
        "Price": price,
        "PE": pe_ratio,
        "ROE %": roe,
        "Quant Score": score,
        "Signal": signal
    }

def fetch_watchlist_data(ticker_list):
    results = []
    with ThreadPoolExecutor(max_workers=min(len(ticker_list), 6)) as executor:
        future_map = {executor.submit(process_ticker, sym): sym for sym in ticker_list}
        for future in as_completed(future_map):
            res = future.result()
            if res:
                results.append(res)
    return results

# ==========================================
# DASHBOARD INTERFACE
# ==========================================
st.markdown("<h1 class='hero-title'>NSE Local Paper Trading Terminal</h1>", unsafe_allow_html=True)
st.caption("No Demat Account or Broker API Keys Required")

with st.sidebar:
    st.header("⚙️ Settings")
    symbols_input = st.text_input(
        "Watchlist Tickers (NSE):", 
        value="RELIANCE, TCS, HDFCBANK, INFY, TATAMOTORS, ICICIBANK"
    )
    if st.button("Reset Portfolio Balance"):
        st.session_state.cash_balance = 1000000.0
        st.session_state.portfolio = {}
        st.session_state.trade_log = []
        st.rerun()

ticker_list = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]

if ticker_list:
    with st.spinner("Fetching live market prices & running quant calculations..."):
        market_data = fetch_watchlist_data(ticker_list)

    if market_data:
        df = pd.DataFrame(market_data)

        # Portfolio Summary Metrics
        portfolio_val = st.session_state.cash_balance
        for sym, pos in st.session_state.portfolio.items():
            sym_match = df[df['Symbol'] == sym]
            c_price = sym_match['Price'].iloc[0] if not sym_match.empty else pos['avg_price']
            portfolio_val += (pos['qty'] * c_price)

        m1, m2, m3 = st.columns(3)
        m1.metric("Available Cash", f"₹{st.session_state.cash_balance:,.2f}")
        m2.metric("Total Portfolio Value", f"₹{portfolio_val:,.2f}")
        m3.metric("Active Holdings", len(st.session_state.portfolio))

        tab_scan, tab_holdings, tab_logs = st.tabs(["📊 Algo Scan & Execution", "💼 My Paper Portfolio", "📜 Trade Ledger"])

        with tab_scan:
            st.subheader("Quantitative Analysis & Trade Execution")
            for _, row in df.iterrows():
                sig = row['Signal']
                color = "🟢" if sig == "BUY" else ("🔴" if sig == "SELL" else "🟡")
                
                with st.expander(f"{color} {row['Company']} ({row['Symbol']}) — ₹{row['Price']:,.2f} | Score: {row['Quant Score']}/100"):
                    c1, c2, c3 = st.columns([1, 1, 2])
                    c1.metric("PE Ratio", f"{row['PE']:.2f}" if row['PE'] > 0 else "N/A")
                    c2.metric("ROE", f"{row['ROE %']:.1f}%")

                    # Buy Execution Button
                    if sig == "BUY" and row['Symbol'] not in st.session_state.portfolio:
                        if c3.button(f"Execute Paper Buy for {row['Symbol']}", key=f"buy_{row['Symbol']}"):
                            allocation = st.session_state.cash_balance * 0.15  # Allocate 15% per position
                            qty = int(allocation // row['Price'])
                            
                            if qty > 0:
                                cost = qty * row['Price']
                                st.session_state.cash_balance -= cost
                                st.session_state.portfolio[row['Symbol']] = {
                                    "qty": qty,
                                    "avg_price": row['Price'],
                                    "sl": row['Price'] * 0.95,
                                    "target": row['Price'] * 1.15
                                }
                                st.session_state.trade_log.append({
                                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "action": "BUY",
                                    "symbol": row['Symbol'],
                                    "qty": qty,
                                    "price": row['Price']
                                })
                                st.success(f"Bought {qty} shares of {row['Symbol']} at ₹{row['Price']:,.2f}")
                                st.rerun()

                    # Sell Execution Button
                    elif row['Symbol'] in st.session_state.portfolio:
                        if c3.button(f"Liquidate Position for {row['Symbol']}", key=f"sell_{row['Symbol']}"):
                            pos = st.session_state.portfolio.pop(row['Symbol'])
                            revenue = pos['qty'] * row['Price']
                            st.session_state.cash_balance += revenue
                            pnl = revenue - (pos['qty'] * pos['avg_price'])
                            
                            st.session_state.trade_log.append({
                                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "action": "SELL",
                                "symbol": row['Symbol'],
                                "qty": pos['qty'],
                                "price": row['Price'],
                                "pnl": pnl
                            })
                            st.warning(f"Sold {pos['qty']} shares of {row['Symbol']}. Realized PnL: ₹{pnl:,.2f}")
                            st.rerun()

        with tab_holdings:
            st.subheader("Current Virtual Positions")
            if st.session_state.portfolio:
                p_rows = []
                for sym, pos in st.session_state.portfolio.items():
                    sym_match = df[df['Symbol'] == sym]
                    c_price = sym_match['Price'].iloc[0] if not sym_match.empty else pos['avg_price']
                    val = pos['qty'] * c_price
                    pnl = val - (pos['qty'] * pos['avg_price'])
                    
                    p_rows.append({
                        "Symbol": sym,
                        "Quantity": pos['qty'],
                        "Avg Buy Price": f"₹{pos['avg_price']:,.2f}",
                        "Current Price": f"₹{c_price:,.2f}",
                        "Position Value": f"₹{val:,.2f}",
                        "Unrealized PnL": f"₹{pnl:,.2f}"
                    })
                st.dataframe(pd.DataFrame(p_rows), use_container_width=True)
            else:
                st.info("No active positions in your paper portfolio.")

        with tab_logs:
            st.subheader("Order Audit History")
            if st.session_state.trade_log:
                st.dataframe(pd.DataFrame(st.session_state.trade_log), use_container_width=True)
            else:
                st.info("No trades executed yet.")
