import os
import time
import pandas as pd
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# -------------------------------------------------------------------
# 1. INITIALIZATION & CREDENTIALS
# -------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY") or st.secrets.get("ALPACA_API_KEY", None)
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY", None)

if not API_KEY or not SECRET_KEY:
    st.error("⚠️ Alpaca API credentials missing. Configure environment variables.")
    st.stop()

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

st.set_page_config(page_title="Production Quant Engine", layout="wide")
st.title("🛡️ Institutional Intraday Quant Engine & Scanner")
st_autorefresh(interval=5000, key="quant_engine_loop")

# Session State for Local Order State Machine & Audit
if "audit_log" not in st.session_state:
    st.session_state.audit_log = []
if "daily_starting_equity" not in st.session_state:
    st.session_state.daily_starting_equity = None

# -------------------------------------------------------------------
# 2. DYNAMIC UNIVERSE & QUANTITATIVE INDICATORS
# -------------------------------------------------------------------
# Expanded Universe (Top Liquid US Tech & Large Cap)
TICKER_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", 
    "NFLX", "INTC", "PYPL", "BAC", "JPM", "DIS", "XOM", "COP", "PFE"
]

SLIPPAGE_PENALTY_PCT = 0.0005  # 0.05% artificial friction simulation
MAX_CAPITAL_PER_TRADE = 100.0  # Strict $100 allocation limit
DAILY_KILL_SWITCH_PCT = 0.03   # Shut down trading if daily equity drops 3%

def Compute_Quantitative_Edge(symbol: str):
    """
    Computes ATR, VWAP, and EMA metrics to find statistical anomalies.
    Returns metrics dictionary if stock meets liquidity thresholds.
    """
    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            limit=40
        )
        bars = data_client.get_stock_bars(request)
        df = bars.df
        if df.empty or len(df) < 20:
            return None

        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['typical_price'] * df['volume']
        
        vwap = df['pv'].sum() / df['volume'].sum()
        latest_price = df['close'].iloc[-1]
        
        # Fast & Slow EMAs
        ema_fast = df['close'].ewm(span=5, adjust=False).mean().iloc[-1]
        ema_slow = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        
        # Average True Range (ATR - 14) for Volatility-Based Position Guard
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        
        # Total Volume Filter (Ensure Liquidity)
        total_vol = df['volume'].sum()
        if total_vol < 10000:  # Minimum volume filter
            return None

        return {
            "symbol": symbol,
            "price": latest_price,
            "vwap": vwap,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "atr": atr,
            "volume": total_vol
        }
    except Exception:
        return None

# -------------------------------------------------------------------
# 3. ORDER STATE MACHINE & FRICTION ROUTER
# -------------------------------------------------------------------
def Route_Order_With_Friction(symbol: str, side: OrderSide, price: float, qty: int, reason: str):
    """
    Applies friction penalties, verifies order limits, and submits extended-hours orders.
    """
    try:
        # Apply Slippage Penalty for Paper Simulation Realism
        if side == OrderSide.BUY:
            execution_limit = round(price * (1 + SLIPPAGE_PENALTY_PCT), 2)
        else:
            execution_limit = round(price * (1 - SLIPPAGE_PENALTY_PCT), 2)

        order_req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=execution_limit,
            time_in_force=TimeInForce.DAY,
            extended_hours=True
        )

        trading_client.submit_order(order_req)
        
        st.session_state.audit_log.insert(0, {
            "Time": pd.Timestamp.now().strftime("%H:%M:%S"),
            "Symbol": symbol,
            "Side": side.value.upper(),
            "Qty": qty,
            "Execution Limit": f"${execution_limit:.2f}",
            "Raw Price": f"${price:.2f}",
            "Reason": reason
        })
        st.toast(f"⚡ ORDER EXECUTED: {side.value.upper()} {qty} {symbol} @ ${execution_limit:.2f}")
        return True
    except Exception as e:
        st.error(f"Order Failure ({symbol}): {str(e)}")
        return False

# -------------------------------------------------------------------
# 4. PORTFOLIO RISK & KILL SWITCH CONTROLS
# -------------------------------------------------------------------
account = trading_client.get_account()
current_equity = float(account.equity)

if st.session_state.daily_starting_equity is None:
    st.session_state.daily_starting_equity = current_equity

daily_drawdown = (st.session_state.daily_starting_equity - current_equity) / st.session_state.daily_starting_equity

st.sidebar.header("🛡️ Portfolio Risk Controls")
bot_active = st.sidebar.toggle("🟢 Active Trading Engine", value=False)
st.sidebar.metric("Daily Drawdown", f"{daily_drawdown*100:.2f}%", delta_color="inverse")

# Emergency Daily Drawdown Kill Switch (-3% Hard Limit)
if daily_drawdown >= DAILY_KILL_SWITCH_PCT:
    bot_active = False
    st.error("🚨 EMERGENCY KILL SWITCH TRIGGERED: Daily Drawdown Exceeded 3%. Bot Deactivated.")
    trading_client.cancel_orders()

# -------------------------------------------------------------------
# 5. UNIVERSE SCANNER & SIGNAL GENERATION
# -------------------------------------------------------------------
raw_positions = trading_client.get_all_positions()
positions = {p.symbol: {"qty": int(p.qty), "avg_entry": float(p.avg_entry_price), "pnl_pct": float(p.unrealized_plpc)} for p in raw_positions}

open_orders = trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
pending_symbols = [o.symbol for o in open_orders]

scan_results = []

for symbol in TICKER_UNIVERSE:
    data = Compute_Quantitative_Edge(symbol)
    if not data:
        continue

    price = data["price"]
    vwap = data["vwap"]
    ema_f = data["ema_fast"]
    ema_s = data["ema_slow"]
    atr = data["atr"]

    pos_info = positions.get(symbol, {"qty": 0, "avg_entry": 0.0, "pnl_pct": 0.0})
    qty = pos_info["qty"]
    pnl_pct = pos_info["pnl_pct"]

    # Dynamic Capital Position Sizing ($100 cap per trade)
    target_qty = int(MAX_CAPITAL_PER_TRADE // price)

    # Risk Rules
    stop_loss = pnl_pct <= -0.008  # Hard -0.8% Stop Loss
    take_profit = pnl_pct >= 0.015  # Hard +1.5% Take Profit

    # Alpha Triggers (VWAP Confirmation + EMA Fast Crossover + Volatility Filter)
    buy_edge = (ema_f > ema_s) and (price > vwap) and (atr > 0.05) and (qty == 0) and (target_qty >= 1) and (symbol not in pending_symbols)
    sell_edge = ((ema_f < ema_s) or (price < vwap)) and (qty > 0)

    signal = "NEUTRAL"
    if stop_loss:
        signal = "🛑 HARD STOP-LOSS"
    elif take_profit:
        signal = "🎯 TAKE PROFIT"
    elif buy_edge:
        signal = f"🟢 BUY ({target_qty} SHRS)"
    elif sell_edge:
        signal = "🔴 EXIT SIGNAL"

    scan_results.append({
        "Symbol": symbol,
        "Price": f"${price:.2f}",
        "VWAP": f"${vwap:.2f}",
        "EMA(5/20)": f"${ema_f:.2f} / ${ema_s:.2f}",
        "ATR": f"${atr:.2f}",
        "Position": qty,
        "PnL (%)": f"{pnl_pct*100:+.2f}%" if qty > 0 else "0.00%",
        "Signal": signal
    })

    # AUTOMATED ROUTING ENGINE
    if bot_active:
        if stop_loss:
            Route_Order_With_Friction(symbol, OrderSide.SELL, price, qty, "Risk Engine: Hard Stop-Loss Trigger")
        elif take_profit:
            Route_Order_With_Friction(symbol, OrderSide.SELL, price, qty, "Risk Engine: Take-Profit Target Reached")
        elif buy_edge:
            Route_Order_With_Friction(symbol, OrderSide.BUY, price, target_qty, "Alpha Engine: VWAP + EMA Trend Alignment")
        elif sell_edge:
            Route_Order_With_Friction(symbol, OrderSide.SELL, price, qty, "Alpha Engine: Trend Breakdown Exit")

# -------------------------------------------------------------------
# 6. DASHBOARD PRESENTATION
# -------------------------------------------------------------------
tab_scan, tab_account, tab_logs = st.tabs(["🔍 Full Universe Scanner", "💼 Active Portfolio", "📜 Execution Audit Engine"])

with tab_scan:
    st.subheader(f"Scanning Universe ({len(scan_results)} Active Liquid Tickers)")
    if scan_results:
        st.dataframe(pd.DataFrame(scan_results), use_container_width=True)

with tab_account:
    col1, col2, col3 = st.columns(3)
    col1.metric("Equity", f"${float(account.equity):,.2f}")
    col2.metric("Buying Power", f"${float(account.buying_power):,.2f}")
    col3.metric("Open Positions", len(raw_positions))

with tab_logs:
    st.subheader("Order State Audit Log (Including Friction Overhead)")
    if st.session_state.audit_log:
        st.dataframe(pd.DataFrame(st.session_state.audit_log), use_container_width=True)
    else:
        st.info("No orders logged in this session.")
