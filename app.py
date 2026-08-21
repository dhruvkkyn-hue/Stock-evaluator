import os
import time
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

# Alpaca API SDK
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# 1. Environment Credentials
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY") or st.secrets.get("ALPACA_API_KEY", None)
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY", None)

if not API_KEY or not SECRET_KEY:
    st.error("⚠️ Alpaca API Keys missing in .env or Streamlit Secrets!")
    st.stop()

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# 2. Page Config & High-Frequency Auto Refresh (3 Seconds)
st.set_page_config(page_title="High-Precision Scalper Engine", layout="wide")
st.title("⚡ Institutional-Grade Intraday & Extended-Hours Scalper")
st_autorefresh(interval=3000, key="scalper_loop")

# Session State Initialization to Maintain Execution Memory Across Reruns
if "trade_audit" not in st.session_state:
    st.session_state.trade_audit = []

# 3. High-Precision Indicator Math
def Get_Market_Metrics(symbol: str):
    """
    Retrieves 1-minute historical data and calculates EMA trend strength, Fast RSI, and VWAP.
    """
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            limit=30
        )
        bars = data_client.get_stock_bars(req)
        df = bars.df
        if df.empty or len(df) < 15:
            return None

        closes = df['close']
        volumes = df['volume']
        highs = df['high']
        lows = df['low']

        ema_fast = closes.ewm(span=5, adjust=False).mean().iloc[-1]
        ema_slow = closes.ewm(span=20, adjust=False).mean().iloc[-1]

        # Fast RSI (7 Period)
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=7).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=7).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).iloc[-1]

        # Volume Weighted Average Price (VWAP)
        typical_price = (highs + lows + closes) / 3
        vwap = (typical_price * volumes).sum() / volumes.sum()

        latest_price = closes.iloc[-1]

        return {
            "price": latest_price,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi": rsi,
            "vwap": vwap
        }
    except Exception:
        return None

# 4. Ultra-Fast Execution Router
def Execute_Order(symbol: str, side: OrderSide, price: float, qty: int, reason: str):
    """
    Places Market-Aggressive Extended Hours Limit Orders for immediate execution fills.
    """
    try:
        # Cross spread for instant fill: Buy @ Ask (+0.1%), Sell @ Bid (-0.1%)
        limit_price = round(price * 1.001, 2) if side == OrderSide.BUY else round(price * 0.999, 2)

        order_req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=limit_price,
            time_in_force=TimeInForce.DAY,
            extended_hours=True
        )

        trading_client.submit_order(order_req)

        # Audit Trail Logging
        st.session_state.trade_audit.insert(0, {
            "Time": pd.Timestamp.now().strftime("%H:%M:%S"),
            "Symbol": symbol,
            "Action": side.value.upper(),
            "Qty": qty,
            "Fill Limit": f"${limit_price:.2f}",
            "Reason": reason
        })
        st.toast(f"⚡ EXECUTED {side.value.upper()} {qty} shares of {symbol} @ ${limit_price:.2f}")
        return True
    except Exception as e:
        st.error(f"Execution Error ({symbol}): {str(e)}")
        return False

# 5. Dashboard Sidebar Controls
st.sidebar.header("🕹️ Quantitative Controls")
bot_active = st.sidebar.toggle("🟢 Activate Auto-Trading Engine", value=False)
shares_per_trade = st.sidebar.number_input("Shares Per Trade", min_value=1, max_value=100, value=5)

# Scalping Parameters
STOP_LOSS_PCT = 0.005    # Tight 0.5% Stop Loss
TAKE_PROFIT_PCT = 0.010  # 1.0% Profit Target

watchlist = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "AMZN"]

# Retrieve Live Positions & Open Orders State
positions = trading_client.get_all_positions()
active_positions = {p.symbol: {"qty": int(p.qty), "avg_entry": float(p.avg_entry_price), "unrealized_pnl": float(p.unrealized_pl)} for p in positions}

open_orders = trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
pending_buy_symbols = [o.symbol for o in open_orders if o.side == OrderSide.BUY]

# Emergency Controls
st.sidebar.markdown("---")
if st.sidebar.button("🚨 EMERGENCY: CANCEL ALL & LIQUIDATE"):
    trading_client.cancel_orders()
    for sym, pos in active_positions.items():
        if pos["qty"] > 0:
            trading_client.close_position(sym)
    st.sidebar.success("All pending orders cancelled and positions closed.")

# UI Tabs
tab_signals, tab_positions, tab_audit = st.tabs(["⚡ Live Signal Matrix", "💼 Active Positions & Risk", "📜 Execution Audit Trail"])

with tab_signals:
    st.subheader("Real-Time Multi-Stock Signal Stream")
    matrix = []

    for symbol in watchlist:
        metrics = Get_Market_Metrics(symbol)
        if metrics:
            price = metrics["price"]
            ema_f = metrics["ema_fast"]
            ema_s = metrics["ema_slow"]
            rsi = metrics["rsi"]
            vwap = metrics["vwap"]

            holding_data = active_positions.get(symbol, {"qty": 0, "avg_entry": 0.0, "unrealized_pnl": 0.0})
            holding_qty = holding_data["qty"]
            avg_entry = holding_data["avg_entry"]

            # Calculate Exact PnL Percentage
            pnl_pct = 0.0
            if holding_qty > 0 and avg_entry > 0:
                pnl_pct = (price - avg_entry) / avg_entry

            # --- DYNAMIC PROFIT/LOSS & ENTRY/EXIT MATH ---
            is_stop_loss = (holding_qty > 0) and (pnl_pct <= -STOP_LOSS_PCT)
            is_take_profit = (holding_qty > 0) and (pnl_pct >= TAKE_PROFIT_PCT)

            # ENTRY MATH: Fast EMA > Slow EMA AND Price >= VWAP AND RSI oversold/neutral (< 55)
            # GUARD: Must hold 0 shares AND have NO pending buy order in flight
            buy_signal = (ema_f > ema_s) and (price >= vwap) and (rsi < 55) and (holding_qty == 0) and (symbol not in pending_buy_symbols)

            # EXIT MATH: Fast EMA breaks below Slow EMA OR RSI overbought (> 65)
            sell_signal = ((ema_f < ema_s) or (rsi > 65)) and (holding_qty > 0)

            status = "NEUTRAL"
            if is_stop_loss:
                status = "🛑 STOP LOSS TRIGGER"
            elif is_take_profit:
                status = "🎯 TAKE PROFIT TRIGGER"
            elif buy_signal:
                status = "🟢 STRONG BUY"
            elif sell_signal:
                status = "🔴 EXIT SIGNAL"

            matrix.append({
                "Symbol": symbol,
                "Price": f"${price:.2f}",
                "EMA(5)": f"${ema_f:.2f}",
                "EMA(20)": f"${ema_s:.2f}",
                "RSI(7)": f"{rsi:.1f}",
                "Position PnL": f"{pnl_pct*100:+.2f}%" if holding_qty > 0 else "0.00%",
                "Holdings": holding_qty,
                "Status": status
            })

            # AUTOMATED SCALPER EXECUTION ENGINE
            if bot_active:
                # 1. FORCE EXIT ON STOP LOSS
                if is_stop_loss:
                    Execute_Order(symbol, OrderSide.SELL, price, holding_qty, f"HARD STOP LOSS HIT ({pnl_pct*100:.2f}%)")

                # 2. FORCE EXIT ON TAKE PROFIT
                elif is_take_profit:
                    Execute_Order(symbol, OrderSide.SELL, price, holding_qty, f"TAKE PROFIT TARGET REACHED (+{pnl_pct*100:.2f}%)")

                # 3. ENTER MOMENTUM BUY
                elif buy_signal:
                    Execute_Order(symbol, OrderSide.BUY, price, shares_per_trade, f"Fast EMA Breakout & VWAP Support")

                # 4. EXIT ON TREND REVERSAL
                elif sell_signal:
                    Execute_Order(symbol, OrderSide.SELL, price, holding_qty, f"Trend Reversal / RSI Exit Trigger")

    st.table(pd.DataFrame(matrix))

with tab_positions:
    st.subheader("Live Portfolio Holdings & Account Equity")
    acc = trading_client.get_account()

    col1, col2, col3 = st.columns(3)
    col1.metric("Equity", f"${float(acc.equity):,.2f}")
    col2.metric("Buying Power", f"${float(acc.buying_power):,.2f}")
    col3.metric("Daytrade Count", acc.daytrade_count)

    st.markdown("---")
    if positions:
        pos_df = pd.DataFrame([{
            "Symbol": p.symbol,
            "Qty": p.qty,
            "Avg Entry": f"${float(p.avg_entry_price):.2f}",
            "Current Price": f"${float(p.current_price):.2f}",
            "Unrealized P/L ($)": f"${float(p.unrealized_pl):,.2f}",
            "Unrealized P/L (%)": f"{float(p.unrealized_plpc)*100:+.2f}%"
        } for p in positions])
        st.dataframe(pos_df, use_container_width=True)
    else:
        st.info("No open positions currently in portfolio.")

with tab_audit:
    st.subheader("Real-Time Execution Audit Trail")
    if st.session_state.trade_audit:
        st.dataframe(pd.DataFrame(st.session_state.trade_audit), use_container_width=True)
    else:
        st.info("No trades executed in current session.")
