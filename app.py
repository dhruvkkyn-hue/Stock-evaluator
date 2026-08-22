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

# --- 1. CORE SYSTEM CONFIG ---
st.set_page_config(page_title="Goated Institutional Terminal", layout="wide", page_icon="🏦")
st_autorefresh(interval=20000, key="bot_heartbeat") # Low-latency refresh

try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
    IS_PAPER = st.secrets.get("IS_PAPER", True)
    
    trading_client = TradingClient(API_KEY, API_SECRET, paper=IS_PAPER)
    data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
except Exception:
    st.error("⚠️ SECRETS ERROR: Add ALPACA_KEY and ALPACA_SECRET to Streamlit Secrets.")
    st.stop()

# --- 2. ALPHA ENGINE (High-Efficiency Vectorized Logic) ---
class AlphaEngine:
    @staticmethod
    def analyze_batch(df):
        if df is None or df.empty: return df
        df = df.copy()
        
        # 1. Reset Multi-index if needed (Alpaca returns MultiIndex [symbol, timestamp])
        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()
            df.set_index('timestamp', inplace=True)

        # 2. Institutional VWAP (Calculated per symbol)
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        
        # Vectorized VWAP per symbol
        df['vwap'] = df.groupby('symbol', group_keys=False).apply(
            lambda x: x['pv'].cumsum() / x['volume'].cumsum()
        )
        
        # 3. Confluence Indicators (Fast EMA 9 / Slow EMA 21)
        df['ema_f'] = df.groupby('symbol')['close'].transform(lambda x: x.ewm(span=9, adjust=False).mean())
        df['ema_s'] = df.groupby('symbol')['close'].transform(lambda x: x.ewm(span=21, adjust=False).mean())
        
        # 4. Volatility Sizing (ATR)
        def get_atr(group):
            tr = pd.concat([
                group['high'] - group['low'], 
                np.abs(group['high'] - group['close'].shift()), 
                np.abs(group['low'] - group['close'].shift())
            ], axis=1).max(axis=1)
            return tr.rolling(14).mean()
        
        df['atr'] = df.groupby('symbol', group_keys=False).apply(get_atr)
        
        # 5. FRAMEWORK: Confluence Signal
        df['signal'] = 0
        df.loc[(df['close'] > df['vwap']) & (df['ema_f'] > df['ema_s']), 'signal'] = 1  # Long
        df.loc[(df['close'] < df['vwap']) & (df['ema_f'] < df['ema_s']), 'signal'] = -1 # Short
        
        return df

# --- 3. UI DASHBOARD & ACCOUNT METRICS ---
acc = trading_client.get_account()
st.title("🏛️ GOATED Institutional Command Center")

# Account Metrics Header
c1, c2, c3, c4 = st.columns(4)
c1.metric("Buying Power", f"${float(acc.buying_power):,.2f}")
c2.metric("Portfolio Value", f"${float(acc.portfolio_value):,.2f}")
c3.metric("Daily P/L", f"${float(acc.equity) - float(acc.last_equity):,.2f}")
if c4.button("🚨 PANIC: LIQUIDATE ALL", use_container_width=True):
    trading_client.close_all_positions(cancel_orders=True)
    st.warning("All positions liquidated.")

# Sidebar Configuration
st.sidebar.header("🕹️ Bot Configuration")
bot_active = st.sidebar.toggle("⚡ ACTIVATE AUTONOMOUS BOT", value=False)
ext_hours = st.sidebar.toggle("🕙 Extended Hours Support", value=True)

# Extended Watchlist
default_watchlist = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "AMZN", "META", "GOOGL", "NFLX", "QQQ", "SPY", "COIN", "PLTR", "SNOW", "SQ", "PYPL", "BA", "DIS", "V"]
watchlist = st.sidebar.multiselect("Active Watchlist", default_watchlist, default=default_watchlist[:15])

# Execution Tabs
tab_monitor, tab_manual = st.tabs(["📡 Live Signals & Bot", "⌨️ Manual Execution Terminal"])

with tab_monitor:
    if watchlist:
        # BATCH DATA FETCH (Prevents individual stock loading errors)
        start_dt = datetime.now() - timedelta(hours=24)
        try:
            req = StockBarsRequest(symbol_or_symbols=watchlist, timeframe=TimeFrame.Minute, start=start_dt)
            raw_data = data_client.get_stock_bars(req).df
            
            # Run Engine
            df = AlphaEngine.analyze_batch(raw_data)
            latest_data = df.groupby('symbol').tail(1).reset_index()
            
            # Format Thinking Logic
            def get_thinking(row):
                if row['signal'] == 1: return "BULLISH: Entry Triggered (Price > VWAP + Trend UP)"
                if row['signal'] == -1: return "BEARISH: Short Triggered (Price < VWAP + Trend DOWN)"
                return "NEUTRAL: Waiting for Confluence"
            
            display_df = latest_data[['symbol', 'close', 'vwap', 'signal', 'atr']].copy()
            display_df['Thinking Engine'] = display_df.apply(get_thinking, axis=1)
            
            # Styled Dataframe (Now works with Matplotlib installed)
            st.dataframe(
                display_df.style.background_gradient(subset=['signal'], cmap='RdYlGn'), 
                use_container_width=True
            )

            # --- AUTONOMOUS BOT EXECUTION ---
            if bot_active:
                for _, row in display_df.iterrows():
                    sym = row['symbol']
                    sig = row['signal']
                    price = row['close']
                    atr = row['atr']
                    
                    # Check Current State
                    try:
                        pos = trading_client.get_open_position(sym)
                        current_side = 1 if int(pos.qty) > 0 else -1
                    except:
                        current_side = 0

                    # Execution Decision
                    if sig != current_side:
                        if current_side != 0: 
                            trading_client.close_position(sym)
                        
                        if sig != 0:
                            # Vol-Adjusted Position Sizing (Risk 1% of equity)
                            risk_dollars = float(acc.equity) * 0.01 
                            stop_dist = atr if atr > (price * 0.005) else (price * 0.01)
                            qty = int(risk_dollars / stop_dist)
                            
                            if qty > 0:
                                trading_client.submit_order(MarketOrderRequest(
                                    symbol=sym, qty=qty, 
                                    side=OrderSide.BUY if sig == 1 else OrderSide.SELL,
                                    time_in_force=TimeInForce.GTC, extended_hours=ext_hours
                                ))
                                st.toast(f"AUTO-TRADER: {sym} Order Placed")

        except Exception as e:
            st.error(f"Data Sync Error: {e}")

with tab_manual:
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Quick Override Order")
        m_sym = st.text_input("Symbol", "NVDA")
        m_qty = st.number_input("Shares", 1, 10000, 10)
        m_side = st.selectbox("Action", ["BUY", "SELL"])
        if st.button("SEND MARKET ORDER", use_container_width=True):
            trading_client.submit_order(MarketOrderRequest(
                symbol=m_sym, qty=m_qty, 
                side=OrderSide.BUY if m_side == "BUY" else OrderSide.SELL, 
                time_in_force=TimeInForce.GTC, extended_hours=ext_hours
            ))
            st.success(f"Manual {m_side} for {m_sym} executed.")

    with col_b:
        st.subheader("Current Open Positions")
        positions = trading_client.get_all_positions()
        if positions:
            pos_data = [{
                'Symbol': p.symbol, 
                'Qty': p.qty, 
                'Price': p.current_price, 
                'P/L %': f"{(float(p.unrealized_plpc)*100):.2f}%"
            } for p in positions]
            st.table(pos_data)
        else:
            st.info("No active positions.")
