import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# Alpaca SDK
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- 1. SYSTEM INITIALIZATION ---
st.set_page_config(page_title="Apex Institutional Terminal", layout="wide", page_icon="🏦")
st_autorefresh(interval=15000, key="bot_heartbeat") # 15-second high-speed refresh

try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
    IS_PAPER = st.secrets.get("IS_PAPER", True)
    
    trading_client = TradingClient(API_KEY, API_SECRET, paper=IS_PAPER)
    data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
except Exception:
    st.error("⚠️ SECRETS ERROR: Add ALPACA_KEY and ALPACA_SECRET to Streamlit Secrets.")
    st.stop()

# --- 2. THE ALPHA ENGINE (Fixed for Duplicate Labels) ---
class AlphaEngine:
    @staticmethod
    def analyze_batch(df):
        """Fixes 'Duplicate Labels' by processing within the MultiIndex structure."""
        if df is None or df.empty: return None
        
        # Ensure we are working with a clean copy and symbol-timestamp index
        df = df.copy()
        
        # 1. Vectorized Indicators per Symbol (The 'Magic' for 40+ stocks)
        # We use groupby(level=0) because level 0 is 'symbol' in Alpaca's MultiIndex
        df['ema_f'] = df.groupby(level=0)['close'].transform(lambda x: x.ewm(span=9, adjust=False).mean())
        df['ema_s'] = df.groupby(level=0)['close'].transform(lambda x: x.ewm(span=21, adjust=False).mean())
        
        # 2. Daily Resetting VWAP
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        
        # Extract date from index level 1 (timestamp)
        df['date'] = df.index.get_level_values(1).date
        
        # Group by symbol AND date for the institutional daily reset
        gb_vwap = df.groupby([df.index.get_level_values(0), 'date'])
        df['vwap'] = gb_vwap['pv'].cumsum() / gb_vwap['volume'].cumsum()
        
        # 3. Volatility (ATR)
        def get_atr(group):
            tr = pd.concat([
                group['high'] - group['low'], 
                np.abs(group['high'] - group['close'].shift()), 
                np.abs(group['low'] - group['close'].shift())
            ], axis=1).max(axis=1)
            return tr.rolling(14).mean()
        
        df['atr'] = df.groupby(level=0, group_keys=False).apply(get_atr)
        
        # 4. SIGNAL FRAMEWORK
        df['signal'] = 0
        df.loc[(df['close'] > df['vwap']) & (df['ema_f'] > df['ema_s']), 'signal'] = 1  # Long
        df.loc[(df['close'] < df['vwap']) & (df['ema_f'] < df['ema_s']), 'signal'] = -1 # Short
        
        return df

# --- 3. UI DASHBOARD & METRICS ---
acc = trading_client.get_account()
st.title("🏛️ APEX Institutional Command Center")

# Fast Action Header
h1, h2, h3, h4 = st.columns([1,1,1,1.5])
h1.metric("Buying Power", f"${float(acc.buying_power):,.2f}")
h2.metric("Portfolio Value", f"${float(acc.portfolio_value):,.2f}")
h3.metric("Daily P/L", f"${float(acc.equity) - float(acc.last_equity):,.2f}")

with h4:
    st.write("") # Alignment
    if st.button("🚨 EMERGENCY: LIQUIDATE ALL POSITIONS", use_container_width=True, type="primary"):
        trading_client.close_all_positions(cancel_orders=True)
        st.toast("SIGNAL SENT: ALL POSITIONS CLOSED")

# Sidebar Configuration
st.sidebar.header("🕹️ Bot Configuration")
bot_active = st.sidebar.toggle("⚡ ACTIVATE AUTONOMOUS BOT", value=False)
ext_hours = st.sidebar.toggle("🕙 Extended Hours Support", value=True)

# Support for 40+ symbols
default_symbols = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "AMZN", "META", "GOOGL", "NFLX", "QQQ", "SPY", "COIN", "PLTR", "SNOW", "SQ", "PYPL", "BA", "DIS", "V", "JPM", "GS", "WMT", "COST"]
watchlist = st.sidebar.multiselect("Active Monitor", default_symbols, default=default_symbols[:15])

# Execution Tabs
tab_mon, tab_exec = st.tabs(["📡 Live Alpha Feed", "⌨️ Manual Execution Terminal"])

with tab_mon:
    if watchlist:
        # High-Speed Batch Fetch
        start_dt = datetime.now() - timedelta(hours=24)
        try:
            req = StockBarsRequest(symbol_or_symbols=watchlist, timeframe=TimeFrame.Minute, start=start_dt)
            raw_df = data_client.get_stock_bars(req).df
            
            # Process Batch
            processed_df = AlphaEngine.analyze_batch(raw_df)
            # Take the last row for each symbol
            latest = processed_df.groupby(level=0).tail(1).reset_index()
            
            # Formatted Intelligence Table
            display = latest[['symbol', 'close', 'vwap', 'signal', 'atr']].copy()
            
            def get_reasoning(row):
                if row['signal'] == 1: return "🔥 BULLISH: Price > VWAP & Trend UP"
                if row['signal'] == -1: return "🩸 BEARISH: Price < VWAP & Trend DOWN"
                return "⚪ NEUTRAL: Waiting for Confluence"
            
            display['Engine Thought'] = display.apply(get_reasoning, axis=1)
            
            # The "Boss" Table
            st.dataframe(
                display.style.background_gradient(subset=['signal'], cmap='RdYlGn'),
                use_container_width=True, height=500
            )

            # --- AUTONOMOUS EXECUTION LOGIC ---
            if bot_active:
                for _, row in display.iterrows():
                    sym, sig, price, atr = row['symbol'], row['signal'], row['close'], row['atr']
                    
                    try:
                        pos = trading_client.get_open_position(sym)
                        current_side = 1 if int(pos.qty) > 0 else -1
                    except:
                        current_side = 0

                    if sig != current_side:
                        # 1. Flip position or close
                        if current_side != 0: 
                            trading_client.close_position(sym)
                        
                        # 2. Enter new position
                        if sig != 0:
                            # Volatility Adjusted Sizing (Risk 1% of Equity)
                            risk_usd = float(acc.equity) * 0.01
                            # Minimum stop distance is 0.5% or ATR
                            stop_dist = max(atr, price * 0.005)
                            qty = int(risk_usd / stop_dist)
                            
                            if qty > 0:
                                trading_client.submit_order(MarketOrderRequest(
                                    symbol=sym, qty=qty, 
                                    side=OrderSide.BUY if sig == 1 else OrderSide.SELL,
                                    time_in_force=TimeInForce.GTC, extended_hours=ext_hours
                                ))
                                st.toast(f"EXECUTED: {sym} {'Long' if sig==1 else 'Short'}")

        except Exception as e:
            st.error(f"Critical System Sync Error: {e}")

with tab_exec:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Manual Market Override")
        msym = st.text_input("Symbol", "NVDA")
        mqty = st.number_input("Shares", 1, 10000, 10)
        maction = st.selectbox("Action", ["BUY", "SELL"])
        if st.button("SEND COMMAND", use_container_width=True):
            trading_client.submit_order(MarketOrderRequest(
                symbol=msym, qty=mqty, side=OrderSide.BUY if maction=="BUY" else OrderSide.SELL,
                time_in_force=TimeInForce.GTC, extended_hours=ext_hours
            ))
            st.success(f"Manual {maction} for {msym} complete.")

    with c2:
        st.subheader("Active Exposure")
        curr_pos = trading_client.get_all_positions()
        if curr_pos:
            st.dataframe(pd.DataFrame([{
                'Symbol': p.symbol, 'Qty': p.qty, 'Entry': p.avg_entry_price, 
                'Price': p.current_price, 'Unrealized P/L %': f"{(float(p.unrealized_plpc)*100):.2f}%"
            } for p in curr_pos]), use_container_width=True)
        else:
            st.info("No active exposure.")
