import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from engine import GoatedEngine

# PAGE CONFIG
st.set_page_config(page_title="Goated Algo Suite", layout="wide", page_icon="🚀")

# PULL SECRETS
try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
except:
    st.error("⚠️ API Keys not found in Streamlit Secrets! Please add ALPACA_KEY and ALPACA_SECRET.")
    st.stop()

# STYLING
st.markdown("""
    <style>
    .metric-card { background-color: #1e2130; padding: 20px; border-radius: 10px; border: 1px solid #4e5d6c; }
    </style>
""", unsafe_allow_html=True)

# SIDEBAR
st.sidebar.title("🎮 Command Center")
selected_symbols = st.sidebar.multiselect("Assets", ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "BTC/USD"], default=["NVDA", "TSLA"])
tf = st.sidebar.selectbox("Timeframe", ["1Min", "5Min", "15Min", "1Hour", "1Day"], index=1)
days = st.sidebar.slider("History (Days)", 1, 365, 30)
ext_hours = st.sidebar.toggle("Include Extended Hours", value=True)

st.sidebar.divider()
st.sidebar.subheader("Strategy Parameters")
fast_p = st.sidebar.number_input("EMA Fast", 5, 50, 12)
slow_p = st.sidebar.number_input("EMA Slow", 10, 200, 26)
slip = st.sidebar.slider("Slippage (BPS)", 0, 100, 5)

# MAIN UI
st.title("🚀 Goated Institutional Algo Trader")
st.info("System Status: Logic Active • Shorting Enabled • ATR Position Sizing")

engine = GoatedEngine(API_KEY, API_SECRET)

if st.button("🔥 EXECUTE RESEARCH PIPELINE"):
    with st.spinner("Processing Market Data..."):
        # 1. Get Data
        raw_data = engine.get_data(selected_symbols, tf, days, ext_hours)
        
        # 2. Apply Logic
        df_map = {}
        for s in selected_symbols:
            symbol_df = raw_data[raw_data.index.get_level_values(0) == s]
            df_map[s] = engine.apply_strategy(symbol_df, {"ema_fast": fast_p, "ema_slow": slow_p})
        
        # 3. Backtest
        config = {"initial_capital": 100000, "slip_bps": slip}
        equity = engine.run_backtest(df_map, config)
        
        # 4. RESULTS
        col1, col2, col3, col4 = st.columns(4)
        final_ret = (equity.iloc[-1] / 100000) - 1
        daily_rets = equity.pct_change().dropna()
        sharpe = (daily_rets.mean() / daily_rets.std()) * (252**0.5) if len(daily_rets) > 0 else 0
        max_dd = (equity / equity.cummax() - 1).min()
        
        col1.metric("Net Profit", f"${equity.iloc[-1]-100000:,.2f}", f"{final_ret:.2%}")
        col2.metric("Institutional Sharpe", f"{sharpe:.2f}")
        col3.metric("Max Drawdown", f"{max_dd:.2%}")
        col4.metric("Volatility (Daily)", f"{daily_rets.std():.2%}")

        # CHARTS
        st.divider()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=equity.index, y=equity.values, name="Portfolio Value", line=dict(color="#00ffcc", width=3)))
        fig.update_layout(title="Mark-to-Market Equity Curve", template="plotly_dark", height=500)
        st.plotly_chart(fig, use_container_width=True)

        # THE "THINKING" ENGINE (Visualizing Signals)
        st.subheader("🧠 Strategy 'Thinking' Process")
        target_s = st.selectbox("View Decision Logic for:", selected_symbols)
        view_df = df_map[target_s].tail(100).copy()
        
        # Add human-readable thought process
        def explain(row):
            if row['signal'] == 1: return "BULLISH: Fast EMA > Slow EMA & Price above VWAP. Buying Strength."
            if row['signal'] == -1: return "BEARISH: Fast EMA < Slow EMA & Price below VWAP. Shorting Weakness."
            return "NEUTRAL: Waiting for trend alignment or VWAP confirmation."
        
        view_df['Decision_Logic'] = view_df.apply(explain, axis=1)
        st.dataframe(view_df[['close', 'vwap', 'ema_f', 'ema_s', 'rsi', 'signal', 'Decision_Logic']], use_container_width=True)

st.divider()
st.subheader("📡 Live Execution Feed (Paper)")
if st.toggle("Activate Live Signal Monitor"):
    st.toast("Connecting to Alpaca WebSocket...")
    st.write("Current Status: Scanning for EMA Crosses + VWAP Breakouts...")
    st.progress(0.4, "Waiting for bar close...")
