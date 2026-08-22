import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time

# Alpaca Imports
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass

# --- 1. ARCHITECTURE: ALPHA ENGINE ---
class AlphaEngine:
    """The Intelligence: Decisions based on Confluence"""
    @staticmethod
    def get_signals(df):
        df = df.copy()
        # 1. Institutional VWAP
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        df['vwap'] = df['pv'].cumsum() / df['volume'].cumsum() # Reset handled by data slice
        
        # 2. Momentum & Trend
        df['ema_fast'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # 3. Volatility (ATR)
        tr = pd.concat([df['high'] - df['low'], 
                        np.abs(df['high'] - df['close'].shift()), 
                        np.abs(df['low'] - df['close'].shift())], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        
        # 4. Framework Logic
        df['signal'] = 0 
        # LONG: Price > VWAP AND Fast EMA > Slow EMA
        long_mask = (df['close'] > df['vwap']) & (df['ema_fast'] > df['ema_slow'])
        # SHORT: Price < VWAP AND Fast EMA < Slow EMA
        short_mask = (df['close'] < df['vwap']) & (df['ema_fast'] < df['ema_slow'])
        
        df.loc[long_mask, 'signal'] = 1
        df.loc[short_mask, 'signal'] = -1
        return df

# --- 2. ARCHITECTURE: RISK ENGINE ---
class RiskManager:
    """The Bodyguard: Protects the Capital"""
    def __init__(self, buying_power):
        self.max_trade_pct = 0.10 # 10% of buying power per trade
        self.buying_power = float(buying_power)

    def calculate_qty(self, price, atr):
        # Risk 1% of total buying power per ATR stop distance
        risk_per_share = atr if atr > 0 else price * 0.02
        target_risk_dollars = self.buying_power * 0.01 
        qty = target_risk_dollars / risk_per_share
        
        # Cap by maximum trade percentage
        max_shares = (self.buying_power * self.max_trade_pct) / price
        return int(min(qty, max_shares))

# --- 3. STREAMLIT UI & LIVE LOGIC ---
st.set_page_config(page_title="Goated Command Center", layout="wide", page_icon="🏦")

# Initialize Clients
try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
    trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
    data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
except:
    st.error("Invalid API Keys in Secrets.")
    st.stop()

# Dashboard Header
st.title("🏛️ Institutional Trading Terminal")
st.caption(f"System Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Connection: Stable")

# Sidebar - Mode & Settings
st.sidebar.header("🕹️ Control Mode")
bot_mode = st.sidebar.radio("Strategy Mode", ["Manual Only", "Autonomous Alpha"])
ext_hours = st.sidebar.toggle("Extended Hours Execution", value=True)
selected_symbols = st.sidebar.multiselect("Active Watchlist", ["AAPL", "NVDA", "TSLA", "AMD", "MSFT", "QQQ", "SPY"], default=["NVDA", "TSLA"])

# Top Row Metrics
account = trading_client.get_account()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Buying Power", f"${float(account.buying_power):,.2f}")
m2.metric("Portfolio Value", f"${float(account.portfolio_value):,.2f}")
m3.metric("Daily P/L", f"${float(account.equity) - float(account.last_equity):,.2f}")
m4.metric("Status", "PAPER" if trading_client.paper else "LIVE")

# Main Dashboard Tabs
tab_dash, tab_manual, tab_logs = st.tabs(["📊 Live Market Monitor", "⌨️ Manual Execution", "📜 Order History"])

with tab_dash:
    st.subheader("Autonomous Confluence Monitor")
    live_cols = st.columns(len(selected_symbols) if selected_symbols else 1)
    
    for i, symbol in enumerate(selected_symbols):
        with live_cols[i]:
            # Fetch Data
            start_dt = datetime.now() - timedelta(hours=6)
            bars = data_client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start_dt
            )).df
            bars.index = bars.index.get_level_values(1)
            
            # Run Alpha Engine
            analyzed = AlphaEngine.get_signals(bars)
            latest = analyzed.iloc[-1]
            
            # Indicator Visuals
            st.metric(symbol, f"${latest.close:.2f}", f"{latest.signal}", delta_color="normal")
            
            # Logic "Thinking" Engine Display
            if latest.signal == 1:
                st.success("BULLISH: Price > VWAP + Trend UP")
            elif latest.signal == -1:
                st.error("BEARISH: Price < VWAP + Trend DOWN")
            else:
                st.warning("NEUTRAL: No Confluence")
            
            # --- AUTO-PILOT EXECUTION ---
            if bot_mode == "Autonomous Alpha":
                try:
                    pos = trading_client.get_open_position(symbol)
                    current_side = 1 if int(pos.qty) > 0 else -1
                except:
                    current_side = 0
                
                if latest.signal != current_side:
                    if current_side != 0:
                        trading_client.close_position(symbol)
                        st.toast(f"Liquidated {symbol} position.")
                    
                    if latest.signal != 0:
                        risk_engine = RiskManager(account.buying_power)
                        qty = risk_engine.calculate_qty(latest.close, latest.atr)
                        if qty > 0:
                            trading_client.submit_order(MarketOrderRequest(
                                symbol=symbol, qty=qty, 
                                side=OrderSide.BUY if latest.signal == 1 else OrderSide.SELL,
                                time_in_force=TimeInForce.GTC,
                                extended_hours=ext_hours
                            ))
                            st.toast(f"Opened {latest.signal} position on {symbol}")

with tab_manual:
    st.subheader("Quick Market Override")
    c1, c2, c3, c4 = st.columns(4)
    man_sym = c1.text_input("Symbol", "NVDA")
    man_qty = c2.number_input("Qty", 1, 1000, 10)
    man_side = c3.selectbox("Side", ["BUY", "SELL"])
    
    if c4.button("🚀 SUBMIT MARKET ORDER"):
        try:
            trading_client.submit_order(MarketOrderRequest(
                symbol=man_sym, qty=man_qty, 
                side=OrderSide.BUY if man_side == "BUY" else OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                extended_hours=ext_hours
            ))
            st.success(f"Manual Order sent for {man_sym}")
        except Exception as e:
            st.error(f"Execution Failed: {e}")

    st.divider()
    st.subheader("Current Open Positions")
    positions = trading_client.get_all_positions()
    if positions:
        pos_df = pd.DataFrame([{
            'Symbol': p.symbol, 'Qty': p.qty, 'Side': p.side, 
            'Entry': p.avg_entry_price, 'Market': p.current_price,
            'P/L %': f"{(float(p.unrealized_plpc)*100):.2f}%"
        } for p in positions])
        st.dataframe(pos_df, use_container_width=True)
    else:
        st.info("No active positions.")

with tab_logs:
    st.subheader("Recent Activity")
    orders = trading_client.get_orders()
    order_data = [{
        'Time': o.created_at.strftime('%H:%M:%S'),
        'Symbol': o.symbol, 'Side': o.side, 'Qty': o.qty, 'Status': o.status
    } for o in orders]
    st.table(order_data)

# Auto-Refresh to keep the bot alive and the dashboard live
time.sleep(30)
st.rerun()
