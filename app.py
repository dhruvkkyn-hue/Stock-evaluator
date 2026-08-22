import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
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
st_autorefresh(interval=20000, key="bot_heartbeat") # 20-second low-latency refresh

try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
    IS_PAPER = st.secrets.get("IS_PAPER", True)
    
    trading_client = TradingClient(API_KEY, API_SECRET, paper=IS_PAPER)
    data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
except:
    st.error("⚠️ SECRETS ERROR: Add ALPACA_KEY and ALPACA_SECRET to Streamlit Secrets.")
    st.stop()

# --- 2. THE ALPHA ENGINE (High-Efficiency Vectorized Logic) ---
class AlphaEngine:
    @staticmethod
    def analyze_batch(df):
        """Processes 40+ stocks simultaneously without loops."""
        if df.empty: return df
        df = df.copy()
        
        # Institutional VWAP (Vectorized per symbol)
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        # Groupby symbol and date to reset VWAP daily
        df['date'] = df.index.get_level_values(1).date
        gb = df.groupby(['symbol', 'date'])
        df['vwap'] = gb['pv'].cumsum() / gb['volume'].cumsum()
        
        # Confluence Indicators
        df['ema_f'] = df.groupby('symbol')['close'].transform(lambda x: x.ewm(span=9, adjust=False).mean())
        df['ema_s'] = df.groupby('symbol')['close'].transform(lambda x: x.ewm(span=21, adjust=False).mean())
        
        # Volatility Sizing (ATR)
        def get_atr(x):
            tr = pd.concat([x['high'] - x['low'], 
                            np.abs(x['high'] - x['close'].shift()), 
                            np.abs(x['low'] - x['close'].shift())], axis=1).max(axis=1)
            return tr.rolling(14).mean()
        df['atr'] = df.groupby('symbol', group_keys=False).apply(get_atr)
        
        # FRAMEWORK: Confluence Signal
        df['signal'] = 0
        df.loc[(df['close'] > df['vwap']) & (df['ema_f'] > df['ema_s']), 'signal'] = 1  # Bullish
        df.loc[(df['close'] < df['vwap']) & (df['ema_f'] < df['ema_s']), 'signal'] = -1 # Bearish
        
        return df

# --- 3. DASHBOARD HEADER ---
acc = trading_client.get_account()
st.title("🏛️ GOATED Institutional Command Center")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Buying Power", f"${float(acc.buying_power):,.2f}")
c2.metric("Equity", f"${float(acc.equity):,.2f}")
c3.metric("Daily P/L", f"${float(acc.equity) - float(acc.last_equity):,.2f}")
c4.button("🚨 PANIC: LIQUIDATE ALL", on_click=lambda: trading_client.close_all_positions(cancel_orders=True), use_container_width=True)

# --- 4. SIDEBAR COMMANDS ---
st.sidebar.header("🕹️ Bot Configuration")
bot_active = st.sidebar.toggle("⚡ ACTIVATE AUTONOMOUS BOT", value=False)
ext_hours = st.sidebar.toggle("🕙 Extended Hours Support", value=True)

# Extended Watchlist (Supports 40+ symbols)
default_watchlist = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "AMZN", "META", "GOOGL", "NFLX", "QQQ", "SPY", "COIN", "PLTR", "SNOW", "SQ", "PYPL", "BA", "DIS", "T", "V"]
watchlist = st.sidebar.multiselect("Watchlist (Batch Processing)", default_watchlist, default=default_watchlist[:15])

# --- 5. EXECUTION TABS ---
tab_monitor, tab_manual = st.tabs(["📡 Live Data & Signals", "⌨️ Manual Execution Terminal"])

with tab_monitor:
    if watchlist:
        # BATCH DATA FETCH (The "Secret Sauce" for low latency)
        start_dt = datetime.now() - timedelta(hours=24) # Get enough for indicators
        try:
            req = StockBarsRequest(symbol_or_symbols=watchlist, timeframe=TimeFrame.Minute, start=start_dt)
            raw_data = data_client.get_stock_bars(req).df
            
            # Analyze All
            df = AlphaEngine.analyze_batch(raw_data)
            latest_data = df.groupby('symbol').tail(1)
            
            # Create a high-density dashboard table
            display_df = latest_data.reset_index()[['symbol', 'close', 'vwap', 'signal', 'atr']]
            
            def get_thinking(row):
                if row['signal'] == 1: return "BULLISH: Entry Triggered (Price > VWAP + Trend UP)"
                if row['signal'] == -1: return "BEARISH: Short Triggered (Price < VWAP + Trend DOWN)"
                return "NEUTRAL: Waiting for Confluence"
            
            display_df['Thinking Engine'] = display_df.apply(get_thinking, axis=1)
            st.dataframe(display_df.style.background_gradient(subset=['signal'], cmap='RdYlGn'), use_container_width=True)

            # --- AUTO-TRADING LOGIC ---
            if bot_active:
                for index, row in display_df.iterrows():
                    sym = row['symbol']
                    sig = row['signal']
                    price = row['close']
                    
                    try:
                        pos = trading_client.get_open_position(sym)
                        current_side = 1 if int(pos.qty) > 0 else -1
                    except:
                        current_side = 0

                    if sig != current_side:
                        if current_side != 0: trading_client.close_position(sym)
                        if sig != 0:
                            # Vol-Adjusted Position Sizing
                            risk_dollars = float(acc.equity) * 0.01 # Risk 1% of total equity
                            qty = int(risk_dollars / (row['atr'] if row['atr'] > 0 else price * 0.02))
                            if qty > 0:
                                trading_client.submit_order(MarketOrderRequest(
                                    symbol=sym, qty=qty, 
                                    side=OrderSide.BUY if sig == 1 else OrderSide.SELL,
                                    time_in_force=TimeInForce.GTC, extended_hours=ext_hours
                                ))
                                st.toast(f"Bot: {sym} { 'Bought' if sig == 1 else 'Short' }")

        except Exception as e:
            st.error(f"Data Sync Error: {e}")

with tab_manual:
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Manual Market Order")
        m_sym = st.text_input("Symbol (Manual)", "NVDA")
        m_qty = st.number_input("Shares", 1, 10000, 10)
        m_side = st.selectbox("Action", ["BUY", "SELL"])
        if st.button("EXECUTE MANUAL"):
            trading_client.submit_order(MarketOrderRequest(symbol=m_sym, qty=m_qty, side=OrderSide.BUY if m_side == "BUY" else OrderSide.SELL, time_in_force=TimeInForce.GTC, extended_hours=ext_hours))
            st.success("Order Sent.")

    with col_b:
        st.subheader("Open Positions")
        positions = trading_client.get_all_positions()
        if positions:
            st.table([{ 'Symbol': p.symbol, 'Qty': p.qty, 'P/L %': f"{(float(p.unrealized_plpc)*100):.2f}%" } for p in positions])
        else:
            st.write("No positions held.")
