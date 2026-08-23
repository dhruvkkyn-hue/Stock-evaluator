import streamlit as st
from engine import TradingEngine

# 1. Setup Secrets
try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
except Exception as e:
    st.error("Missing Alpaca Keys in Secrets!")
    st.stop()

# 2. Persistent Global State
# We check if it's 'None' to avoid the AttributeError you saw
if 'engine' not in st.session_state or st.session_state.engine is None:
    st.session_state.engine = TradingEngine(API_KEY, API_SECRET, ["AAPL", "NVDA", "TSLA"])

engine = st.session_state.engine

# 3. Safe UI Check
st.title("🏛️ Apex Predator v5")

# Check status safely
is_active = getattr(engine, 'is_running', False)
st.write(f"Bot Status: {'🟢 ACTIVE' if is_active else '🔴 OFFLINE'}")
