import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ==========================================
# PAGE CONFIG & STATE
# ==========================================
st.set_page_config(page_title="Automated Paper Trader", layout="wide", page_icon="🤖")

if "cash_balance" not in st.session_state:
    st.session_state.cash_balance = 1000000.0  # ₹10 Lakhs Virtual Cash
if "portfolio" not in st.session_state:
    st.session_state.portfolio = {}  # {symbol: {qty, avg_price, sl, target}}
if "trade_log" not in st.session_state:
    st.session_state.trade_log = []

# ==========================================
# REAL-TIME MARKET DATA & AUTO-EXECUTION ENGINE
# ==========================================
def fetch_ticker_data(symbol):
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

    pe = float(info.get('trailingPE', 0.0) or info.get('forwardPE', 0.0) or 0.0)
    roe = float(info.get('returnOnEquity', 0.0) or 0.0) * 100

    # Quant Score System (0-100)
    score = 0
    if 0 < pe <= 25: score += 40
    elif 25 < pe <= 40: score += 20
    if roe >= 18: score += 40
    elif roe >= 12: score += 20

    signal = "BUY" if score >= 60 else ("SELL" if score <= 20 else "HOLD")

    return {
        "Symbol": sym_clean,
        "Company": info.get('shortName', sym_clean),
        "Price": price,
        "PE": pe,
        "ROE": roe,
        "Score": score,
        "Signal": signal
    }

def fetch_watchlist(symbols):
    data = {}
    with ThreadPoolExecutor(max_workers=min(len(symbols), 6)) as executor:
        futures = {executor.submit(fetch_ticker_data, sym): sym for sym in symbols}
        for future in as_completed(futures):
            res = future.result()
            if res:
                data[res["Symbol"]] = res
    return data

def run_auto_trade_engine(market_data):
    """Automated Risk & Order Manager: Evaluates active holdings against SL and Target triggers."""
    auto_liquidations = []
    
    for sym, pos in list(st.session_state.portfolio.items()):
        if sym in market_data:
            curr_price = market_data[sym]["Price"]
            
            # 1. Stop-Loss Check
            if curr_price <= pos["sl"]:
                st.session_state.portfolio.pop(sym)
                revenue = pos["qty"] * curr_price
                st.session_state.cash_balance += revenue
                pnl = revenue - (pos["qty"] * pos["avg_price"])
                
                log = {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "action": "AUTO-SELL (STOP LOSS)",
                    "symbol": sym,
                    "qty": pos["qty"],
                    "price": curr_price,
                    "pnl": pnl
                }
                st.session_state.trade_log.append(log)
                auto_liquidations.append(f"🚨 STOP LOSS HIT: Liquidated {sym} at ₹{curr_price:,.2f} (PnL: ₹{pnl:,.2f})")

            # 2. Target Check
            elif curr_price >= pos["target"]:
                st.session_state.portfolio.pop(sym)
                revenue = pos["qty"] * curr_price
                st.session_state.cash_balance += revenue
                pnl = revenue - (pos["qty"] * pos["avg_price"])
                
                log = {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "action": "AUTO-SELL (TARGET)",
                    "symbol": sym,
                    "qty": pos["qty"],
                    "price": curr_price,
                    "pnl": pnl
                }
                st.session_state.trade_log.append(log)
                auto_liquidations.append(f"🎯 TARGET REACHED: Liquidated {sym} at ₹{curr_price:,.2f} (PnL: ₹{pnl:,.2f})")
                
    return auto_liquidations

# ==========================================
# DASHBOARD LAYOUT
# ==========================================
st.title("🤖 Fully Automated Paper Trader")

with st.sidebar:
    symbols_input = st.text_input("Watchlist (NSE):", "RELIANCE, TCS, HDFCBANK, INFY, TATAMOTORS, ICICIBANK")
    if st.button("Reset Portfolio"):
        st.session_state.cash_balance = 1000000.0
        st.session_state.portfolio = {}
        st.session_state.trade_log = []
        st.rerun()

watchlist = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]

if watchlist:
    market_data = fetch_watchlist(watchlist)
    
    # Run Auto-Trader Risk Manager
    notifications = run_auto_trade_engine(market_data)
    for note in notifications:
        st.toast(note, icon="⚡")

    # Metrics Overview
    port_val = st.session_state.cash_balance
    for sym, pos in st.session_state.portfolio.items():
        c_price = market_data[sym]["Price"] if sym in market_data else pos["avg_price"]
        port_val += (pos["qty"] * c_price)

    col1, col2, col3 = st.columns(3)
    col1.metric("Available Cash", f"₹{st.session_state.cash_balance:,.2f}")
    col2.metric("Portfolio Valuation", f"₹{port_val:,.2f}")
    col3.metric("Open Positions", len(st.session_state.portfolio))

    tab1, tab2, tab3 = st.tabs(["📊 Market & Signal Scanner", "💼 Active Positions", "📜 Auto-Trade Audit Log"])

    with tab1:
        st.subheader("Quantitative Buy & Sell Signals")
        for sym, item in market_data.items():
            sig = item["Signal"]
            color = "🟢" if sig == "BUY" else ("🔴" if sig == "SELL" else "🟡")
            
            with st.expander(f"{color} {item['Company']} ({sym}) — ₹{item['Price']:,.2f} | Score: {item['Score']}/100"):
                st.write(f"**P/E:** {item['PE']:.2f} | **ROE:** {item['ROE']:.2f}% | **Signal:** {sig}")
                
                if sig == "BUY" and sym not in st.session_state.portfolio:
                    if st.button(f"Buy 15% Allocation ({sym})", key=f"b_{sym}"):
                        alloc = st.session_state.cash_balance * 0.15
                        qty = int(alloc // item["Price"])
                        if qty > 0:
                            st.session_state.cash_balance -= (qty * item["Price"])
                            st.session_state.portfolio[sym] = {
                                "qty": qty,
                                "avg_price": item["Price"],
                                "sl": item["Price"] * 0.95,     # 5% Stop-Loss
                                "target": item["Price"] * 1.15   # 15% Target
                            }
                            st.session_state.trade_log.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "action": "BUY",
                                "symbol": sym,
                                "qty": qty,
                                "price": item["Price"]
                            })
                            st.rerun()

    with tab2:
        st.subheader("Holdings with Active Risk Triggers")
        if st.session_state.portfolio:
            rows = []
            for sym, pos in st.session_state.portfolio.items():
                c_price = market_data[sym]["Price"] if sym in market_data else pos["avg_price"]
                pnl = (pos["qty"] * c_price) - (pos["qty"] * pos["avg_price"])
                rows.append({
                    "Symbol": sym,
                    "Qty": pos["qty"],
                    "Avg Price": f"₹{pos['avg_price']:,.2f}",
                    "Live Price": f"₹{c_price:,.2f}",
                    "PnL": f"₹{pnl:,.2f}",
                    "Stop-Loss (Auto-Sell)": f"₹{pos['sl']:,.2f}",
                    "Target (Auto-Sell)": f"₹{pos['target']:,.2f}"
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No active open positions.")

    with tab3:
        st.subheader("Automated Execution Logs")
        if st.session_state.trade_log:
            st.dataframe(pd.DataFrame(st.session_state.trade_log), use_container_width=True)
