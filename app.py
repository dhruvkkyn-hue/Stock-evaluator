import streamlit as st
import pandas as pd
from engine import TradingEngine
from database import TradingDB
from streamlit_autorefresh import st_autorefresh

st.set_page_config(layout="wide", page_title="APEX PREDATOR v5")
st_autorefresh(interval=10000, key="refresh")

# Secrets
try:
    K, S = st.secrets["ALPACA_KEY"], st.secrets["ALPACA_SECRET"]
except:
    st.error("Add ALPACA_KEY and ALPACA_SECRET to Streamlit Secrets.")
    st.stop()

# State Management
if 'engine' not in st.session_state:
    st.session_state.engine = TradingEngine(K, S, ["AAPL", "NVDA", "TSLA", "AMD", "MSFT"])
    st.session_state.db = TradingDB()

en = st.session_state.engine
db = st.session_state.db

# --- UI ---
st.title("🏛️ APEX PREDATOR v5")
c1, c2, c3 = st.columns(3)
c1.metric("Engine", "🟢 RUNNING" if en.is_running else "🔴 STOPPED")
c2.metric("Symbols", len(en.symbols))
c3.metric("Account Mode", "PAPER" if en.paper else "LIVE")

# Sidebar
st.sidebar.title("Controls")
if st.sidebar.button("🚀 START ENGINE"):
    en.start()
if st.sidebar.button("🛑 STOP ENGINE"):
    en.is_running = False
if st.sidebar.button("🚨 PANIC LIQUIDATE", type="primary"):
    en.trade_client.close_all_positions(cancel_orders=True)

# Main View
t1, t2 = st.tabs(["📊 Portfolio", "📜 Trade Audit"])
with t1:
    try:
        acc = en.trade_client.get_account()
        st.write(f"### Buying Power: ${float(acc.buying_power):,.2f}")
        pos = en.trade_client.get_all_positions()
        if pos:
            st.table([{"Sym": p.symbol, "Qty": p.qty, "P/L": p.unrealized_pl} for p in pos])
        else:
            st.info("No active positions.")
    except:
        st.error("Wait... Connecting to Alpaca.")

with t2:
    st.dataframe(db.get_logs(), use_container_width=True)
