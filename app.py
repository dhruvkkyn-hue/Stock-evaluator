import streamlit as st
import pandas as pd
from engine import TradingEngine
from database import TradingDB
from streamlit_autorefresh import st_autorefresh

st.set_page_config(layout="wide", page_title="APEX PREDATOR v5", page_icon="🏦")
st_autorefresh(interval=10000, key="datarefresh")

# API Setup
try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
except:
    st.error("KEYS MISSING: Add ALPACA_KEY and ALPACA_SECRET to Streamlit Secrets.")
    st.stop()

# Persistent Engine
if 'engine' not in st.session_state:
    st.session_state.engine = TradingEngine(API_KEY, API_SECRET, ["AAPL", "NVDA", "TSLA", "AMD", "MSFT"])
    st.session_state.db = TradingDB()

engine = st.session_state.engine
db = st.session_state.db

# --- UI HEADER ---
st.title("🏛️ APEX PREDATOR: Institutional Strategy Console")
status_col, sync_col, mode_col = st.columns(3)

with status_col:
    st.metric("System Status", "🟢 ACTIVE" if engine.is_running else "🔴 OFFLINE")
with sync_col:
    st.metric("Symbols Tracked", len(engine.symbols))
with mode_col:
    st.metric("Trading Mode", "PAPER" if engine.trade_client.account_link else "LIVE")

# --- CONTROLS ---
st.sidebar.header("🕹️ Command Center")
if st.sidebar.button("🚀 BOOT ENGINE", use_container_width=True):
    engine.start()
    st.toast("Worker Process Initialized.")

if st.sidebar.button("🛑 KILL ENGINE", use_container_width=True):
    engine.stop()
    st.toast("Worker Process Terminated.")

if st.sidebar.button("🚨 PANIC: LIQUIDATE ALL", type="primary", use_container_width=True):
    engine.trade_client.close_all_positions(cancel_orders=True)
    st.error("ALL POSITIONS FLATTENED.")

# --- TABS ---
tab_portfolio, tab_ledger, tab_strategy = st.tabs(["💼 Live Portfolio", "📜 Trade Ledger", "📈 Strategy Health"])

with tab_portfolio:
    try:
        acc = engine.trade_client.get_account()
        st.subheader(f"Account Value: ${float(acc.equity):,.2f}")
        
        pos = engine.trade_client.get_all_positions()
        if pos:
            pos_df = pd.DataFrame([{"Symbol": p.symbol, "Qty": p.qty, "Entry": p.avg_entry_price, "P/L": p.unrealized_pl} for p in pos])
            st.table(pos_df)
        else:
            st.info("No open positions.")
    except:
        st.warning("Connecting to Broker...")

with tab_ledger:
    st.subheader("Historical Trade Audit")
    logs = db.get_logs(50)
    if not logs.empty:
        st.dataframe(logs, use_container_width=True)
    else:
        st.info("Waiting for first signal confluence...")

with tab_strategy:
    st.write("Strategy: EMA Crossover + VWAP Confluence")
    st.code("""
    If Price > VWAP AND EMA(9) > EMA(21) => LONG
    If Price < VWAP AND EMA(9) < EMA(21) => SHORT
    Position Sizing: 2% Fixed Fractional
    """)
