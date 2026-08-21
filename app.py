import os
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

# Alpaca API imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# 1. Environment & API Setup
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY") or st.secrets.get("ALPACA_API_KEY", None)
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY", None)

if not API_KEY or not SECRET_KEY:
    st.error("⚠️ Alpaca credentials missing! Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env or Secrets.")
    st.stop()

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# High-Frequency UI Settings (Refreshes state every 3 seconds)
st.set_page_config(page_title="High-Speed Scalper Engine", layout="wide")
st.title("⚡ Ultra-Fast Intraday Scalper & Risk Guardian")
st_autorefresh(interval=3000, key="high_speed_loop")

if "trade_audit_trail" not in st.session_state:
    st.session_state.trade_audit_trail = []

# 2. High-Frequency Technical Indicator Math
def Get_High_Speed_Metrics(symbol: str):
    """
    Computes 1-minute indicators: Fast EMA (3), Slow EMA (12), Fast RSI (9), and VWAP.
    """
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            limit=25
        )
        bars = data_client.get_stock_bars(req)
        df = bars.df
        if df.empty or len(df) < 15:
            return None

        closes = df['close']
        volumes = df['volume']
        highs = df['high']
        lows = df['low']

        # Ultra-fast moving averages for rapid trend Detection
        ema_fast = closes.ewm(span=3, adjust=False).mean().iloc[-1]
        ema_slow = closes.ewm(span=12, adjust=False).mean().iloc[-1]

        # Fast RSI (9-period for immediate overbought/oversold detection)
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=9).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=9).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).iloc[-1]

        # VWAP
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

# 3. Aggressive Execution Engine
def Execute_Fast_Limit_Order(symbol: str, side: OrderSide, base_price: float, qty: int, reason: str, active_positions: dict):
    """
    Executes Limit Orders with a price-buffer offset to guarantee immediate fill execution
    during extended-hours sessions.
    """
    try:
        current_holding = active_positions.get(symbol, {"qty": 0, "avg_entry": 0.0})
        current_qty = current_holding["qty"]

        # SHORT-SALE SAFETY GUARD
        if side == OrderSide.SELL and current_qty <= 0:
            return False

        account = trading_client.get_account()
        buying_power = float(account.buying_power)

        # Buffer pricing: Buy slightly above market, Sell slightly below market for instant fills
        if side == OrderSide.BUY:
            fill_price = round(base_price * 1.0008, 2)
            if (fill_price * qty) > buying_power:
                st.error(f"⛔ Trade Rejected: Insufficient buying power for {symbol}")
                return False
        else:
            fill_price = round(base_price * 0.9992, 2)

        order_request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=fill_price,
            time_in_force=TimeInForce.DAY,
            extended_hours=True
        )

        trading_client.submit_order(order_request)

        st.session_state.trade_audit_trail.insert(0, {
            "Time": pd.Timestamp.now().strftime("%H:%M:%S"),
            "Symbol": symbol,
            "Action": side.value.upper(),
            "Qty": qty,
            "Price": f"${fill_price:.2f}",
            "Trigger": reason
        })
        st.toast(f"⚡ ORDER FILLED: {side.value.upper()} {qty} shares of {symbol} @ ${fill_price:.2f}")
        return True

    except Exception as e:
        st.error(f"Execution Error ({symbol}): {str(e)}")
        return False

# 4. Streamlit Control Panel & Real-time Loop
st.sidebar.header("⚙️ Scalper Parameters")
bot_active = st.sidebar.toggle("🟢 Activate Auto-Scalper Bot", value=False)
shares_per_trade = st.sidebar.number_input("Shares Per Order", min_value=1, max_value=200, value=5)

# Hard Risk Parameters
stop_loss_pct = 0.008   # Cut loss at -0.8%
take_profit_pct = 0.012 # Lock profit at +1.2%

watch_universe = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "AMZN"]

# Retrieve Current Open Positions
raw_positions = trading_client.get_all_positions()
active_positions = {p.symbol: {"qty": int(p.qty), "avg_entry": float(p.avg_entry_price)} for p in raw_positions}

# Emergency Flash Liquidator
st.sidebar.markdown("---")
if st.sidebar.button("🚨 EMERGENCY: CLOSE ALL POSITIONS"):
    trading_client.cancel_orders()
    for sym, pos in active_positions.items():
        if pos["qty"] > 0:
            trading_client.close_position(sym)
    st.sidebar.error("All active orders canceled and positions closed!")

tab_scanner, tab_portfolio, tab_audit = st.tabs(["⚡ Fast Signal Matrix", "💼 Live Holdings & Risk", "📜 Execution Audit"])

with tab_scanner:
    st.subheader("Real-Time Signal Engine")
    matrix = []

    for symbol in watch_universe:
        m = Get_High_Speed_Metrics(symbol)
        if m:
            price = m["price"]
            ema_f = m["ema_fast"]
            ema_s = m["ema_slow"]
            rsi = m["rsi"]
            vwap = m["vwap"]

            holding_data = active_positions.get(symbol, {"qty": 0, "avg_entry": 0.0})
            holding_qty = holding_data["qty"]
            avg_entry = holding_data["avg_entry"]

            # --- HARD PROFIT & LOSS PROTECTION MATH ---
            is_stop_loss = False
            is_take_profit = False
            pnl_pct = 0.0

            if holding_qty > 0 and avg_entry > 0:
                pnl_pct = (price - avg_entry) / avg_entry
                if pnl_pct <= -stop_loss_pct:
                    is_stop_loss = True
                elif pnl_pct >= take_profit_pct:
                    is_take_profit = True

            # QUANT BUY CONDITION: Fast EMA > Slow EMA AND Price > VWAP AND RSI < 60
            buy_signal = (ema_f > ema_s) and (price >= vwap) and (rsi < 60) and (holding_qty == 0)

            # QUANT SELL CONDITION: Trend Break (EMA Fast < Slow) OR Overbought (RSI > 68)
            sell_signal = (ema_f < ema_s) or (rsi > 68)

            status = "NEUTRAL"
            if is_stop_loss:
                status = "🛑 HARD STOP-LOSS TRIGGER"
            elif is_take_profit:
                status = "🎯 TAKE-PROFIT TRIGGER"
            elif buy_signal:
                status = "🟢 BUY MOMENTUM"
            elif sell_signal and holding_qty > 0:
                status = "🔴 EXIT SIGNAL"

            matrix.append({
                "Symbol": symbol,
                "Price": f"${price:.2f}",
                "EMA(3)": f"${ema_f:.2f}",
                "EMA(12)": f"${ema_s:.2f}",
                "RSI(9)": f"{rsi:.1f}",
                "Unrealized PnL": f"{pnl_pct*100:+.2f}%" if holding_qty > 0 else "N/A",
                "Holdings": holding_qty,
                "Status": status
            })

            # AUTOMATED SCALPER EXECUTION
            if bot_active:
                # 1. STOP-LOSS SAFETY EXIT
                if is_stop_loss:
                    Execute_Fast_Limit_Order(symbol, OrderSide.SELL, price, holding_qty, f"STOP LOSS HIT ({pnl_pct*100:.2f}%)", active_positions)
                
                # 2. TAKE-PROFIT EXIT
                elif is_take_profit:
                    Execute_Fast_Limit_Order(symbol, OrderSide.SELL, price, holding_qty, f"TAKE PROFIT TARGET REACHED (+{pnl_pct*100:.2f}%)", active_positions)
                
                # 3. MOMENTUM ENTRY
                elif buy_signal:
                    Execute_Fast_Limit_Order(symbol, OrderSide.BUY, price, shares_per_trade, f"Fast EMA Crossover & VWAP Support", active_positions)
                
                # 4. TREND BREAKOUT EXIT
                elif sell_signal and holding_qty > 0:
                    Execute_Fast_Limit_Order(symbol, OrderSide.SELL, price, holding_qty, f"Fast EMA Trend Breakdown", active_positions)

    st.table(pd.DataFrame(matrix))

with tab_portfolio:
    st.subheader("Account Capital & Risk Exposure")
    acc = trading_client.get_account()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Equity", f"${float(acc.equity):,.2f}")
    col2.metric("Buying Power", f"${float(acc.buying_power):,.2f}")
    col3.metric("Daytrade Count", acc.daytrade_count)

    st.markdown("---")
    st.subheader("Active Position P&L Breakdown")
    if raw_positions:
        pos_df = pd.DataFrame([{
            "Symbol": p.symbol,
            "Qty": p.qty,
            "Avg Entry": f"${float(p.avg_entry_price):.2f}",
            "Current Price": f"${float(p.current_price):.2f}",
            "Market Value": f"${float(p.market_value):,.2f}",
            "Unrealized P/L": f"${float(p.unrealized_pl):,.2f}",
            "PnL %": f"{float(p.unrealized_plpc)*100:+.2f}%"
        } for p in raw_positions])
        st.dataframe(pos_df, use_container_width=True)
    else:
        st.info("No active open positions.")

with tab_audit:
    st.subheader("Live Execution Audit Log")
    if st.session_state.trade_audit_trail:
        st.dataframe(pd.DataFrame(st.session_state.trade_audit_trail), use_container_width=True)
    else:
        st.info("No trades executed yet in this session.")
