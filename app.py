import streamlit as st
import pandas as pd
import numpy as np
import threading
import time
from datetime import datetime, timedelta, timezone
from streamlit_autorefresh import st_autorefresh

# Alpaca SDK
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

# --- 1. THE CONNECTION & SECRETS MANAGER ---
st.set_page_config(page_title="Apex Predator v5", layout="wide", page_icon="🏦")

# Global variables for the bot to use outside of the UI thread
global_bot_logs = []
global_last_check = "Never"

def get_keys():
    try:
        return st.secrets["ALPACA_KEY"], st.secrets["ALPACA_SECRET"]
    except:
        st.error("🔑 KEYS MISSING: Add 'ALPACA_KEY' and 'ALPACA_SECRET' to your Streamlit Secrets.")
        st.stop()

API_KEY, API_SECRET = get_keys()

# --- 2. THE PERSISTENT BOT SERVICE ---
class UnifiedBot:
    def __init__(self, symbols):
        self.symbols = symbols
        self.trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
        self.data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
        self.is_active = False
        self.last_ts = {s: None for s in symbols}
        self.equity_cache = 0.0
        self.pnl_cache = 0.0

    def log(self, msg):
        global global_bot_logs
        ts = datetime.now().strftime("%H:%M:%S")
        global_bot_logs.append(f"[{ts}] {msg}")
        if len(global_bot_logs) > 50: global_bot_logs.pop(0)

    def start_loop(self):
        self.is_active = True
        self.log("🚀 ENGINE START: High-Frequency Monitoring Engaged")
        while self.is_active:
            try:
                global global_last_check
                global_last_check = datetime.now().strftime("%H:%M:%S")
                
                # 1. Broker Sync (Proof of connection)
                acc = self.trading_client.get_account()
                self.equity_cache = float(acc.equity)
                self.pnl_cache = float(acc.equity) - float(acc.last_equity)

                # 2. Market Data Scan
                start_dt = datetime.now(timezone.utc) - timedelta(hours=3)
                req = StockBarsRequest(symbol_or_symbols=self.symbols, timeframe=TimeFrame.Minute, start=start_dt)
                bars = self.data_client.get_stock_bars(req).df
                
                for symbol in self.symbols:
                    df = bars.xs(symbol).iloc[:-1] # Only completed bars
                    latest_ts = df.index[-1]
                    
                    if self.last_ts[symbol] == latest_ts: continue # Already processed
                    
                    # 3. Decision Logic (Juiced Up)
                    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
                    df['ema_9'] = df['close'].ewm(span=9).mean()
                    
                    price = df['close'].iloc[-1]
                    vwap = df['vwap'].iloc[-1]
                    ema = df['ema_9'].iloc[-1]
                    
                    # Confluence Signal
                    signal = 0
                    if price > vwap and price > ema: signal = 1
                    elif price < vwap and price < ema: signal = -1
                    
                    # 4. Order Execution
                    self.execute_trade(symbol, signal, price)
                    self.last_ts[symbol] = latest_ts
                
            except Exception as e:
                self.log(f"⚠️ API ERROR: {str(e)}")
            
            time.sleep(5) # Fast 5-second market heartbeat

    def execute_trade(self, symbol, signal, price):
        try:
            # Check Position
            try:
                pos = self.trading_client.get_open_position(symbol)
                current_side = 1 if int(pos.qty) > 0 else -1
            except:
                current_side = 0

            if signal != current_side:
                # Resolve conflicts (Pending orders)
                orders = self.trading_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
                if any(o.symbol == symbol for o in orders): return

                if current_side != 0:
                    self.trading_client.close_position(symbol)
                    self.log(f"📉 LIQUIDATED {symbol} at ${price}")

                if signal != 0:
                    qty = max(1, int((self.equity_cache * 0.02) / price)) # 2% allocation
                    self.trading_client.submit_order(MarketOrderRequest(
                        symbol=symbol, qty=qty, 
                        side=OrderSide.BUY if signal == 1 else OrderSide.SELL,
                        time_in_force=TimeInForce.GTC, extended_hours=True
                    ))
                    self.log(f"🔥 ENTERED {'LONG' if signal == 1 else 'SHORT'} {symbol} ({qty} shs) @ ${price}")
        except Exception as e:
            self.log(f"❌ TRADE FAILED: {str(e)}")

# --- 3. THE UI DASHBOARD ---
st_autorefresh(interval=5000, key="ui_heartbeat")

if 'bot_instance' not in st.session_state:
    st.session_state.bot_instance = UnifiedBot(["AAPL", "NVDA", "TSLA", "AMD", "MSFT"])

bot = st.session_state.bot_instance

# Header
st.title("🏛️ APEX PREDATOR v5: Institutional Control")
st.write(f"**Bot Status:** {'🟢 ACTIVE' if bot.is_active else '🔴 OFFLINE'} | **Last Sync:** {global_last_check}")

# Metrics Row
c1, c2, c3, c4 = st.columns(4)
c1.metric("Live Equity", f"${bot.equity_cache:,.2f}")
c2.metric("Intraday P/L", f"${bot.pnl_cache:,.2f}")

try:
    pos_list = bot.trading_client.get_all_positions()
    c3.metric("Open Positions", len(pos_list))
except:
    c3.metric("Open Positions", 0)

# Sidebar Controls
st.sidebar.header("🕹️ Bot Controls")
if st.sidebar.button("🚀 BOOT ENGINE", use_container_width=True):
    if not bot.is_active:
        threading.Thread(target=bot.start_loop, daemon=True).start()
        st.toast("Engine Online.")

if st.sidebar.button("🛑 KILL ENGINE", use_container_width=True):
    bot.is_active = False
    st.toast("Engine Offline.")

if st.sidebar.button("🚨 PANIC: LIQUIDATE", type="primary", use_container_width=True):
    bot.trading_client.close_all_positions(cancel_orders=True)
    bot.log("EMERGENCY: ALL POSITIONS FLATTENED.")

# --- 4. REAL-TIME DATA DISPLAYS ---
tab_trades, tab_positions, tab_diagnostics = st.tabs(["📜 Live Trade Ledger", "💼 Active Portfolio", "🔍 Connection Diagnostics"])

with tab_trades:
    st.subheader("High-Frequency Audit Log")
    if not global_bot_logs:
        st.info("Waiting for first trade signal...")
    else:
        for msg in reversed(global_bot_logs):
            if "ENTERED" in msg: st.success(msg)
            elif "LIQUIDATED" in msg: st.error(msg)
            else: st.text(msg)

with tab_positions:
    st.subheader("Broker-Synchronized Positions")
    try:
        pos_data = []
        for p in pos_list:
            pos_data.append({
                "Symbol": p.symbol,
                "Side": p.side.upper(),
                "Qty": p.qty,
                "Market Value": f"${float(p.market_value):,.2f}",
                "Profit/Loss": f"{float(p.unrealized_intraday_plpc)*100:.2f}%"
            })
        if pos_data:
            st.table(pos_data)
        else:
            st.info("No active trades currently.")
    except Exception as e:
        st.warning("Could not sync positions yet.")

with tab_diagnostics:
    st.subheader("API Connection Health")
    try:
        acc_raw = bot.trading_client.get_account()
        st.write("**Account Number:**", acc_raw.account_number)
        st.write("**Currency:**", acc_raw.currency)
        st.write("**Status:**", acc_raw.status)
        st.write("**Buying Power:**", f"${float(acc_raw.buying_power):,.2f}")
        st.success("✅ CONNECTION ESTABLISHED: Alpaca API is responding perfectly.")
    except Exception as e:
        st.error(f"❌ CONNECTION FAILED: {str(e)}")
