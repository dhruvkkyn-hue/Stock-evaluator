import streamlit as st
import threading
from engine import TradingEngine

st.set_page_config(layout="wide", page_title="Institutional Trading Platform")

# Use Secrets for API Keys
API_KEY = st.secrets["ALPACA_KEY"]
API_SECRET = st.secrets["ALPACA_SECRET"]

if "engine" not in st.session_state:
    st.session_state.engine = TradingEngine(API_KEY, API_SECRET, ["AAPL", "NVDA", "TSLA"])

engine = st.session_state.engine

st.title("🏛️ Production Algorithmic Console")

# Dashboard Layout
col1, col2 = st.columns([1, 3])

with col1:
    st.header("Controls")
    if st.button("Start System", use_container_width=True):
        if not engine.is_running:
            thread = threading.Thread(target=engine.run_loop, daemon=True)
            thread.start()
            st.success("Worker Thread Launched")
    
    if st.button("Emergency Stop", type="primary", use_container_width=True):
        engine.is_running = False
        st.warning("Worker Stopping...")

with col2:
    st.header("System Health")
    # Here you would query File 1 (database.py) to show the heartbeat 
    # and trade journal instead of using session_state.
    st.info("System reading from persistent SQLite store...")
