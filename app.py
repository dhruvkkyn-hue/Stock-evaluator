import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
from streamlit_autorefresh import st_autorefresh

# Alpaca Imports
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- 1. CORE CONFIG & SECRETS ---
st.set_page_config(page_title="Goated Terminal", layout="wide", page_icon="🏦")

# Auto-refresh every 30 seconds to run the Auto-Trading logic
st_autorefresh(interval=30000, key="bot_heartbeat")

try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
    # Change this in your Streamlit Secrets to False for real money
    IS_PAPER = st.secrets.get("IS_PAPER", True) 
    
    trading_client = TradingClient(API_KEY, API_SECRET, paper=IS_PAPER)
    data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
except Exception as e:
    st.error(f"Setup Error: {e}. Check your Streamlit Secrets.")
    st.stop()

# --- 2. ALPHA ENGINE: THE CONFLUENCE FRAMEWORK ---
class AlphaEngine:
    @staticmethod
    def analyze(df):
        if df.empty: return df
        df = df.copy()
        
        # Institutional VWAP (Cumulative for the fetched period)
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        df['vwap'] = df['pv'].cumsum() / df['volume'].cumsum()
        
        # Trend Confluence (9/21 EMA Cross)
        df['ema_f'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_s'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # Volatility Sizing (ATR)
        tr = pd.concat([df['high'] - df['low'], 
                        np.abs(df['high'] - df['close'].shift()), 
                        np.abs(df['low'] - df['close'].shift())], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        
        # SIGNAL FRAMEWORK
        # 1 = Long, -1 = Short, 0 = Neutral
        df['signal'] = 0
        df.loc[(df['close'] > df['vwap']) & (df['ema_f'] > df['ema_s']), 'signal'] = 1
        df.loc[(df['close'] < df['vwap']) & (df['ema_f'] < df['ema_s']), 'signal'] = -1
        
        return df

# --- 3. UI: HEADER & ACCOUNT METRICS ---
account = trading_client.get_account()
st.title("🏛️ Goated Institutional Command Center")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Buying Power", f"${float(account.buying_power):,.2f}")
m2.metric("Portfolio Value", f"${float(account.portfolio_value):,.2f}")
m3.metric("Equity", f"${float(account.equity):,.2f}")
# Fixed the Attribute Error here by using the IS_PAPER variable directly
m4.metric("Market Mode", "PAPER" if IS_PAPER else "LIVE")

# --- 4. CONTROL PANEL ---
st.sidebar.header("🕹️ Bot Controls")
bot_active = st.sidebar.toggle("Activate Autonomous Alpha", value=False)
ext_hours = st.sidebar.toggle("Extended Hours Support", value=True)
symbols = st.sidebar.multiselect("Active Watchlist", ["AAPL", "NVDA", "TSLA", "AMD", "MSFT", "QQQ", "SPY"], default=["NVDA", "TSLA"])

# --- 5. MAIN LOGIC: AUTO-TRADING & MONITOR ---
tab_monitor, tab_manual, tab_history = st.tabs(["📡 Live Monitor", "⌨️ Manual Terminal", "📜 History"])

with tab_monitor:
    if not symbols:
        st.info("Add symbols in the sidebar to start monitoring.")
    else:
        cols = st.columns(len(symbols))
        for i, symbol in enumerate(symbols):
            with cols[i]:
                # Data Fetching (Extended Hours included via feed)
                start_dt = datetime.now() - timedelta(hours=8)
                try:
                    bars = data_client.get_stock_bars(StockBarsRequest(
                        symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start_dt
                    )).df
                    bars.index = bars.index.get_level_values(1)
                    
                    df = AlphaEngine.analyze(bars)
                    latest = df.iloc[-1]
                    
                    # Display Signal
                    st.subheader(symbol)
                    st.metric("Price", f"${latest.close:.2f}")
                    
                    if latest.signal == 1:
                        st.success("THINKING: BULLISH (Price > VWAP + Trend UP)")
                    elif latest.signal == -1:
                        st.error("THINKING: BEARISH (Price < VWAP + Trend DOWN)")
                    else:
                        st.warning("THINKING: NEUTRAL (No Confluence)")

                    # --- AUTONOMOUS EXECUTION ---
                    if bot_active:
                        # Check current position
                        try:
                            pos = trading_client.get_open_position(symbol)
                            current_side = 1 if int(pos.qty) > 0 else -1
                        except:
                            current_side = 0

                        # Signal Flip Logic
                        if latest.signal != current_side:
                            if current_side != 0:
                                trading_client.close_position(symbol)
                            
                            if latest.signal != 0:
                                # Volatility Adjusted Sizing (Risk 2% of BP)
                                risk_amt = float(account.buying_power) * 0.02
                                qty = int(risk_amt / (latest.atr if latest.atr > 0 else latest.close * 0.02))
                                
                                trading_client.submit_order(MarketOrderRequest(
                                    symbol=symbol, qty=qty,
                                    side=OrderSide.BUY if latest.signal == 1 else OrderSide.SELL,
                                    time_in_force=TimeInForce.GTC,
                                    extended_hours=ext_hours
                                ))
                                st.toast(f"Bot Executed {symbol} Order")

                except Exception as e:
                    st.error(f"Error loading {symbol}")

with tab_manual:
    st.subheader("Manual Market Override")
    c1, c2, c3 = st.columns(3)
    msym = c1.text_input("Symbol", "NVDA")
    mqty = c2.number_input("Shares", 1, 1000, 10)
    mside = c3.selectbox("Action", ["BUY", "SELL"])
    
    if st.button("🚀 SUBMIT MANUAL ORDER", use_container_width=True):
        try:
            trading_client.submit_order(MarketOrderRequest(
                symbol=msym, qty=mqty, 
                side=OrderSide.BUY if mside == "BUY" else OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                extended_hours=ext_hours
            ))
            st.success("Order Placed Successfully")
        except Exception as e:
            st.error(f"Failed: {e}")

    st.divider()
    st.subheader("Open Positions")
    all_pos = trading_client.get_all_positions()
    if all_pos:
        st.dataframe(pd.DataFrame([{
            'Symbol': p.symbol, 'Qty': p.qty, 'Entry': p.avg_entry_price, 
            'Price': p.current_price, 'P/L %': f"{(float(p.unrealized_plpc)*100):.2f}%"
        } for p in all_pos]), use_container_width=True)
    else:
        st.write("No open positions.")

with tab_history:
    st.subheader("Recent Order Logs")
    orders = trading_client.get_orders()
    if orders:
        st.table([{
            'Time': o.created_at.strftime('%H:%M:%S'), 
            'Symbol': o.symbol, 'Side': o.side, 'Status': o.status
        } for o in orders])
