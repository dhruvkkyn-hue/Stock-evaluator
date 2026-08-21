import os
import streamlit as st
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Load Credentials
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY") or st.secrets.get("ALPACA_API_KEY", None)
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY", None)

if not API_KEY or not SECRET_KEY:
    st.error("⚠️ Alpaca credentials missing! Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env or Secrets.")
    st.stop()

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

st.set_page_config(page_title="High-Frequency Intraday Engine", layout="wide")
st.title("⚡ Ultra-Fast Intraday Quantitative Trader")

# High-frequency engine loop (Refreshes state every 3 seconds for rapid processing)
st_autorefresh(interval=3000, key="hft_refresh_loop")

if "execution_logs" not in st.session_state:
    st.session_state.execution_logs = []

# --- 1. REAL-TIME MULTI-FACTOR MATH ---
def Calculate_Fast_Intraday_Metrics(symbol: str):
    """
    Computes High-Frequency Indicators:
    - 5-period & 20-period Exponential Moving Averages (Fast Momentum Cross)
    - 14-period Fast RSI
    - VWAP (Institutional Benchmark)
    """
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            limit=30
        )
        bars = data_client.get_stock_bars(req)
        df = bars.df
        if df.empty or len(df) < 20:
            return None

        closes = df['close']
        volumes = df['volume']
        highs = df['high']
        lows = df['low']

        # Fast and Slow Moving Averages
        ema_fast = closes.ewm(span=5, adjust=False).mean().iloc[-1]
        ema_slow = closes.ewm(span=20, adjust=False).mean().iloc[-1]

        # VWAP
        typical_price = (highs + lows + closes) / 3
        vwap = (typical_price * volumes).sum() / volumes.sum()

        # Fast RSI (14)
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).iloc[-1]

        latest_price = closes.iloc[-1]

        return {
            "price": latest_price,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "vwap": vwap,
            "rsi": rsi
        }
    except Exception as e:
        return None

# --- 2. DEFENSIVE HIGH-SPEED ORDER ROUTER ---
def Execute_Intraday_Order(symbol: str, side: OrderSide, target_price: float, qty: int, reason: str, active_positions: dict):
    """
    Validates capital limits, prevents illegal short selling, and routes fast-execution limit orders.
    """
    try:
        # SHORT-SALE GUARD: Do not issue a SELL if position quantity is 0
        current_holding_qty = active_positions.get(symbol, 0)
        if side == OrderSide.SELL and current_holding_qty <= 0:
            return False

        account = trading_client.get_account()
        buying_power = float(account.buying_power)
        order_val = target_price * qty

        if side == OrderSide.BUY and order_val > buying_power:
            st.error(f"⛔ Insufficient funds for {symbol}")
            return False

        # Calculate aggressive fill price (Buffer applied to bypass illiquid spreads)
        fill_price = target_price * 1.0005 if side == OrderSide.BUY else target_price * 0.9995

        order_req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=round(fill_price, 2),
            time_in_force=TimeInForce.DAY,
            extended_hours=True
        )

        trading_client.submit_order(order_req)

        st.session_state.execution_logs.insert(0, {
            "Time": pd.Timestamp.now().strftime("%H:%M:%S"),
            "Symbol": symbol,
            "Side": side.value.upper(),
            "Qty": qty,
            "Price": f"${target_price:.2f}",
            "Trigger": reason
        })
        st.toast(f"⚡ ORDER SENT: {side.value.upper()} {symbol} @ ${target_price:.2f}")
        return True

    except Exception as e:
        st.error(f"Execution Error ({symbol}): {str(e)}")
        return False

# --- 3. DASHBOARD CONTROLS & TRADING UNIVERSE ---
st.sidebar.header("⚙️ High-Frequency Engine Settings")
bot_active = st.sidebar.toggle("🟢 Activate Auto Trading Bot", value=False)
shares_per_trade = st.sidebar.number_input("Shares Per Trade", min_value=1, max_value=500, value=10)

# Multi-Stock Intraday Watchlist
watchlist = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "AMZN", "META"]

# Retrieve Current Account Positions to Prevent Short-Sale Violations
raw_positions = trading_client.get_all_positions()
active_positions_map = {p.symbol: int(p.qty) for p in raw_positions}

tab_scanner, tab_portfolio, tab_audit = st.tabs(["⚡ Fast Intraday Scanner", "💼 Account & Positions", "📜 Real-Time Audit Trail"])

with tab_scanner:
    st.subheader("Multi-Stock Intraday Signal Stream")
    matrix = []

    for symbol in watchlist:
        m = Calculate_Fast_Intraday_Metrics(symbol)
        if m:
            price = m["price"]
            ema_fast = m["ema_fast"]
            ema_slow = m["ema_slow"]
            vwap = m["vwap"]
            rsi = m["rsi"]

            # --- PROFIT-ORIENTED INTRADAY MATH ---
            # BUY SIGNAL: Fast EMA crosses Slow EMA upward AND Price > VWAP AND RSI is not overbought (< 65)
            buy_signal = (ema_fast > ema_slow) and (price >= vwap) and (rsi <= 65)

            # SELL SIGNAL: Fast EMA drops below Slow EMA OR RSI >= 70 (Take-profit threshold)
            sell_signal = (ema_fast < ema_slow) or (rsi >= 70)

            holding_qty = active_positions_map.get(symbol, 0)
            status = "HOLD / NEUTRAL"
            if buy_signal:
                status = "🟢 BUY MOMENTUM"
            elif sell_signal and holding_qty > 0:
                status = "🔴 SELL SIGNAL"

            matrix.append({
                "Symbol": symbol,
                "Price": f"${price:.2f}",
                "EMA(5)": f"${ema_fast:.2f}",
                "EMA(20)": f"${ema_slow:.2f}",
                "VWAP": f"${vwap:.2f}",
                "RSI": f"{rsi:.1f}",
                "Holdings": holding_qty,
                "Signal": status
            })

            # AUTO EXECUTION ENGINE
            if bot_active:
                if buy_signal and holding_qty == 0:
                    reason = f"Fast EMA (${ema_fast:.2f}) > Slow EMA (${ema_slow:.2f}) & VWAP Support"
                    Execute_Intraday_Order(symbol, OrderSide.BUY, price, shares_per_trade, reason, active_positions_map)

                elif sell_signal and holding_qty > 0:
                    reason = f"Trend Shift: Fast EMA (${ema_fast:.2f}) < Slow EMA (${ema_slow:.2f}) or RSI ({rsi:.1f}) Exit"
                    Execute_Intraday_Order(symbol, OrderSide.SELL, price, holding_qty, reason, active_positions_map)

    st.table(pd.DataFrame(matrix))

with tab_portfolio:
    st.subheader("Live Holdings & Profit Metrics")
    acc = trading_client.get_account()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Equity", f"${float(acc.equity):,.2f}")
    col2.metric("Buying Power", f"${float(acc.buying_power):,.2f}")
    col3.metric("Daytrade Count", acc.daytrade_count)

    if raw_positions:
        pos_df = pd.DataFrame([{
            "Symbol": p.symbol,
            "Qty": p.qty,
            "Avg Entry": f"${float(p.avg_entry_price):.2f}",
            "Current Price": f"${float(p.current_price):.2f}",
            "Unrealized P/L": f"${float(p.unrealized_pl):,.2f}"
        } for p in raw_positions])
        st.dataframe(pos_df, use_container_width=True)
    else:
        st.info("No active open positions.")

with tab_audit:
    st.subheader("Execution History & Strategy Logs")
    if st.session_state.execution_logs:
        st.dataframe(pd.DataFrame(st.session_state.execution_logs), use_container_width=True)
    else:
        st.info("No execution signals triggered in the current session.")
