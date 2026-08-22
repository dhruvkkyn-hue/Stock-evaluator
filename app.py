import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import threading
import time
import logging
from datetime import datetime, timedelta, timezone
from collections import deque

# Alpaca SDK
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

# --- 1. SYSTEM LOGGING & STATE ---
# We use a global state so the background worker and UI can talk
if 'system_state' not in st.session_state:
    st.session_state.system_state = {
        "is_running": False,
        "logs": deque(maxlen=50),
        "active_positions": {},
        "equity_history": deque(maxlen=100),
        "last_bar_processed": {}, # {symbol: timestamp}
        "account_info": {},
        "strategy_thinking": {}
    }

def log_event(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.system_state["logs"].appendleft(f"[{ts}] {msg}")

# --- 2. CANONICAL STRATEGY (Shared with Backtester) ---
class CanonicalStrategy:
    """Exactly the same logic used in research and production."""
    def __init__(self, params):
        self.params = params

    def compute_signals(self, df):
        df = df.copy()
        # 1. VWAP (Session Reset)
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        df['date'] = df.index.date
        gb = df.groupby('date')
        df['vwap'] = gb['pv'].cumsum() / gb['volume'].cumsum()
        
        # 2. EMA Stack
        df['ema_f'] = df['close'].ewm(span=self.params['fast']).mean()
        df['ema_s'] = df['close'].ewm(span=self.params['slow']).mean()
        
        # 3. ATR (Volatility)
        high_low = df['high'] - df['low']
        high_cp = np.abs(df['high'] - df['close'].shift())
        low_cp = np.abs(df['low'] - df['close'].shift())
        df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()
        
        return df

# --- 3. THE PERSISTENT WORKER ---
class TradingWorker:
    def __init__(self, api_key, api_secret, symbols, is_paper=True):
        self.t_client = TradingClient(api_key, api_secret, paper=is_paper)
        self.d_client = StockHistoricalDataClient(api_key, api_secret)
        self.symbols = symbols
        self.strategy = CanonicalStrategy({"fast": 9, "slow": 21})
        self.running = False

    def run_loop(self):
        log_event("Worker Process Started.")
        while self.running:
            try:
                # 1. Update Account State (Broker Reconciliation)
                acc = self.t_client.get_account()
                st.session_state.system_state["account_info"] = {
                    "equity": float(acc.equity),
                    "buying_power": float(acc.buying_power),
                    "pnl": float(acc.equity) - float(acc.last_equity)
                }
                st.session_state.system_state["equity_history"].append(float(acc.equity))

                # 2. Fetch Data (Warm-up for indicators)
                start_dt = datetime.now(timezone.utc) - timedelta(days=2)
                bars = self.d_client.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=self.symbols, timeframe=TimeFrame.Minute, start=start_dt
                )).df
                
                # 3. Process each symbol
                for symbol in self.symbols:
                    symbol_df = bars.xs(symbol)
                    
                    # --- CRITICAL FIX #3: Only trade on COMPLETED bars ---
                    # Drop the current minute bar (incomplete)
                    completed_bars = symbol_df.iloc[:-1] 
                    latest_ts = completed_bars.index[-1]
                    
                    # --- CRITICAL FIX #2: Idempotency check ---
                    if st.session_state.system_state["last_bar_processed"].get(symbol) == latest_ts:
                        continue # Already handled this minute
                    
                    # Compute Signal
                    df = self.strategy.compute_signals(completed_bars)
                    row = df.iloc[-1]
                    
                    signal = 0
                    if row['close'] > row['vwap'] and row['ema_f'] > row['ema_s']:
                        signal = 1
                    elif row['close'] < row['vwap'] and row['ema_f'] < row['ema_s']:
                        signal = -1
                    
                    st.session_state.system_state["strategy_thinking"][symbol] = {
                        "price": row['close'], "vwap": row['vwap'], "signal": signal
                    }

                    # 4. Check broker state vs target
                    self.reconcile_and_execute(symbol, signal, row)
                    
                    # Mark bar as processed
                    st.session_state.system_state["last_bar_processed"][symbol] = latest_ts

            except Exception as e:
                log_event(f"CRITICAL ERROR: {str(e)}")
            
            time.sleep(10) # High-frequency internal loop

    def reconcile_and_execute(self, symbol, target_signal, data_row):
        # 1. Get existing position
        try:
            pos = self.t_client.get_open_position(symbol)
            current_side = 1 if int(pos.qty) > 0 else -1
        except:
            current_side = 0

        # 2. Logic: If current state != target state
        if target_signal != current_side:
            # Check for pending orders to prevent duplicate "insufficient qty"
            orders = self.t_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
            if any(o.symbol == symbol for o in orders):
                log_event(f"Waiting for pending order on {symbol}")
                return

            if current_side != 0:
                self.t_client.close_position(symbol)
                log_event(f"LIQUIDATING {symbol}")

            if target_signal != 0:
                # Sizing: 2% Risk based on ATR
                equity = float(st.session_state.system_state["account_info"]["equity"])
                risk_amt = equity * 0.02
                qty = int(risk_amt / (data_row['atr'] if data_row['atr'] > 0 else data_row['close']*0.01))
                
                if qty > 0:
                    self.t_client.submit_order(MarketOrderRequest(
                        symbol=symbol, qty=qty, 
                        side=OrderSide.BUY if target_signal == 1 else OrderSide.SELL,
                        time_in_force=TimeInForce.GTC, extended_hours=True
                    ))
                    log_event(f"EXECUTING: {symbol} {'LONG' if target_signal == 1 else 'SHORT'} Qty: {qty}")

# --- 4. STREAMLIT UI ---
st.set_page_config(page_title="Apex Predator v3", layout="wide")

# Dashboard Header
st.title("🏦 Institutional Trading Dashboard")
st.caption("Standalone Execution Engine • Exchange-Time Reconciled • Stop-Based Sizing")

# Sidebar
st.sidebar.header("System Controls")
if st.sidebar.button("🚀 Start Engine"):
    if not st.session_state.system_state["is_running"]:
        worker = TradingWorker(API_KEY, API_SECRET, ["AAPL", "NVDA", "TSLA", "AMD", "MSFT"])
        worker.running = True
        thread = threading.Thread(target=worker.run_loop, daemon=True)
        thread.start()
        st.session_state.system_state["is_running"] = True
        log_event("Engine Powering Up...")

if st.sidebar.button("🛑 Stop Engine"):
    st.session_state.system_state["is_running"] = False
    log_event("Engine Shutdown Requested.")

# --- UI SECTION: LIVE METRICS ---
info = st.session_state.system_state["account_info"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Live Equity", f"${info.get('equity', 0):,.2f}")
c2.metric("Buying Power", f"${info.get('buying_power', 0):,.2f}")
c3.metric("Intraday P/L", f"${info.get('pnl', 0):,.2f}")
c4.metric("Engine Status", "RUNNING" if st.session_state.system_state["is_running"] else "OFFLINE")

# --- UI SECTION: THE "THINKING" ENGINE ---
st.divider()
st.subheader("🧠 Strategy Logic Monitor")
think = st.session_state.system_state["strategy_thinking"]
if think:
    think_df = pd.DataFrame(think).T
    st.dataframe(think_df, use_container_width=True)

# --- UI SECTION: VISIBILITY (The Logs) ---
st.divider()
col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("📡 Execution Audit Feed")
    for log in st.session_state.system_state["logs"]:
        st.text(log)

with col_right:
    st.subheader("📈 Performance Trajectory")
    if len(st.session_state.system_state["equity_history"]) > 1:
        st.line_chart(list(st.session_state.system_state["equity_history"]))

# Final manual Liquidate
if st.button("🚨 EMERGENCY LIQUIDATE ALL", type="primary"):
    trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
    trading_client.close_all_positions(cancel_orders=True)
    log_event("USER MANUALLY LIQUIDATED ALL POSITIONS.")
