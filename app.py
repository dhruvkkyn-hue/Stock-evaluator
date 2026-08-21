import os
import pandas as pd
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from streamlit_autorefresh import st_autorefresh

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# -------------------------------------------------------------------
# 1. SETUP & CREDENTIALS
# -------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY") or st.secrets.get("ALPACA_API_KEY", None)
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY", None)

if not API_KEY or not SECRET_KEY:
    st.error("⚠️ Credentials missing! Add ALPACA_API_KEY and ALPACA_SECRET_KEY.")
    st.stop()

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

st.set_page_config(page_title="Ultra-Low Latency Scalper", layout="wide")
st.title("⚡ Ultra-Low Latency Quant Scalper & Portfolio Monitor")

# Refresh every 1000ms (1 second) for near real-time state
st_autorefresh(interval=1000, key="high_frequency_loop")

if "audit_log" not in st.session_state:
    st.session_state.audit_log = []

# Broad Scanning Universe
TICKER_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
    "NFLX", "INTC", "PYPL", "BAC", "JPM", "DIS", "XOM", "COP", "PFE"
]

MAX_CAPITAL_PER_TRADE = 100.0
SLIPPAGE_PENALTY_PCT = 0.0005

# -------------------------------------------------------------------
# 2. CONCURRENT DATA FETCHING (LOW-LATENCY ENGINE)
# -------------------------------------------------------------------
def Fetch_Single_Ticker_Metrics(symbol: str):
    """
    Worker function executed in parallel to fetch bars and compute indicators.
    """
    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            limit=25
        )
        bars = data_client.get_stock_bars(request)
        df = bars.df
        if df.empty or len(df) < 15:
            return None

        # Extract price values
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['typical_price'] * df['volume']
        vwap = df['pv'].sum() / df['volume'].sum() if df['volume'].sum() > 0 else df['close'].iloc[-1]
        
        latest_price = df['close'].iloc[-1]
        ema_fast = df['close'].ewm(span=5, adjust=False).mean().iloc[-1]
        ema_slow = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        
        # ATR Calculation
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift()).abs(),
            (df['low'] - df['close'].shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(10).mean().iloc[-1]

        return {
            "Symbol": symbol,
            "Price": latest_price,
            "VWAP": vwap,
            "EMA_Fast": ema_fast,
            "EMA_Slow": ema_slow,
            "ATR": atr
        }
    except Exception:
        return None

def Fast_Parallel_Universe_Scan(universe):
    """
    Spawns worker threads to pull all tickers simultaneously in sub-second time.
    """
    results = {}
    with ThreadPoolExecutor(max_workers=len(universe)) as executor:
        out = executor.map(Fetch_Single_Ticker_Metrics, universe)
        for res in out:
            if res:
                results[res["Symbol"]] = res
    return results

# -------------------------------------------------------------------
# 3. REAL-TIME PORTFOLIO & POSITION AUDITOR
# -------------------------------------------------------------------
def Get_Live_Portfolio_State():
    """
    Direct sync with Alpaca account & position state.
    """
    try:
        account = trading_client.get_account()
        positions_raw = trading_client.get_all_positions()
        
        active_pos_map = {}
        for p in positions_raw:
            active_pos_map[p.symbol] = {
                "qty": int(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc)
            }
        return account, active_pos_map, positions_raw
    except Exception as e:
        st.error(f"Portfolio Sync Failure: {e}")
        return None, {}, []

# -------------------------------------------------------------------
# 4. ORDER ROUTING & FRICTION ENGINE
# -------------------------------------------------------------------
def Execute_Order(symbol: str, side: OrderSide, price: float, qty: int, reason: str):
    try:
        limit_price = round(price * (1 + SLIPPAGE_PENALTY_PCT), 2) if side == OrderSide.BUY else round(price * (1 - SLIPPAGE_PENALTY_PCT), 2)
        
        order_req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=limit_price,
            time_in_force=TimeInForce.DAY,
            extended_hours=True
        )
        trading_client.submit_order(order_req)
        
        st.session_state.audit_log.insert(0, {
            "Time": pd.Timestamp.now().strftime("%H:%M:%S"),
            "Symbol": symbol,
            "Side": side.value.upper(),
            "Qty": qty,
            "Limit Price": f"${limit_price:.2f}",
            "Reason": reason
        })
        st.toast(f"⚡ ORDER SENT: {side.value.upper()} {qty} {symbol} @ ${limit_price:.2f}")
    except Exception as e:
        st.error(f"Order Execution Failed ({symbol}): {str(e)}")

# -------------------------------------------------------------------
# 5. MAIN EXECUTION CONTROLLER
# -------------------------------------------------------------------
account, active_pos_map, raw_positions = Get_Live_Portfolio_State()

st.sidebar.header("🕹️ Low-Latency Controller")
bot_active = st.sidebar.toggle("🟢 Activate Engine", value=False)

if account:
    st.sidebar.metric("Account Equity", f"${float(account.equity):,.2f}")
    st.sidebar.metric("Buying Power", f"${float(account.buying_power):,.2f}")

tab_portfolio, tab_signals, tab_logs = st.tabs(["💼 Live Real-Time Portfolio", "⚡ Fast Signal Scanner", "📜 Audit Engine"])

# --- TAB 1: REAL-TIME PORTFOLIO DISPLAY ---
with tab_portfolio:
    st.subheader("Current Active Positions")
    if raw_positions:
        p_data = []
        for p in raw_positions:
            p_data.append({
                "Symbol": p.symbol,
                "Quantity": p.qty,
                "Avg Entry": f"${float(p.avg_entry_price):.2f}",
                "Current Price": f"${float(p.current_price):.2f}",
                "Market Value": f"${float(p.market_value):,.2f}",
                "Unrealized P/L ($)": f"${float(p.unrealized_pl):,.2f}",
                "Unrealized P/L (%)": f"{float(p.unrealized_plpc)*100:+.2f}%"
            })
        st.dataframe(pd.DataFrame(p_data), use_container_width=True)
    else:
        st.info("No active open positions in portfolio.")

# --- TAB 2: PARALLEL SIGNAL SCANNER & BOT EXECUTION ---
with tab_signals:
    st.subheader("Sub-Second Dynamic Market Scanner")
    
    # Run multi-threaded parallel data fetch
    market_snapshot = Fast_Parallel_Universe_Scan(TICKER_UNIVERSE)
    
    open_orders = trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
    pending_symbols = [o.symbol for o in open_orders]

    scan_matrix = []
    
    for symbol, data in market_snapshot.items():
        price = data["Price"]
        vwap = data["VWAP"]
        ema_f = data["EMA_Fast"]
        ema_s = data["EMA_Slow"]
        atr = data["ATR"]

        pos_info = active_pos_map.get(symbol, {"qty": 0, "unrealized_plpc": 0.0})
        qty = pos_info["qty"]
        pnl_pct = pos_info["unrealized_plpc"]

        target_qty = int(MAX_CAPITAL_PER_TRADE // price)

        # Risk Controls
        stop_loss = (qty > 0) and (pnl_pct <= -0.008)
        take_profit = (qty > 0) and (pnl_pct >= 0.015)

        # Signal Triggers
        buy_signal = (ema_f > ema_s) and (price > vwap) and (qty == 0) and (target_qty >= 1) and (symbol not in pending_symbols)
        sell_signal = ((ema_f < ema_s) or (price < vwap)) and (qty > 0)

        status = "HOLDING/NEUTRAL"
        if stop_loss:
            status = "🛑 STOP LOSS"
        elif take_profit:
            status = "🎯 TAKE PROFIT"
        elif buy_signal:
            status = f"🟢 BUY ({target_qty} shrs)"
        elif sell_signal:
            status = "🔴 EXIT SIGNAL"

        scan_matrix.append({
            "Symbol": symbol,
            "Price": f"${price:.2f}",
            "VWAP": f"${vwap:.2f}",
            "EMA Fast/Slow": f"${ema_f:.2f} / ${ema_s:.2f}",
            "Position Qty": qty,
            "Unrealized PnL": f"{pnl_pct*100:+.2f}%" if qty > 0 else "0.00%",
            "Signal": status
        })

        # AUTOMATED BOT ROUTING
        if bot_active:
            if stop_loss:
                Execute_Order(symbol, OrderSide.SELL, price, qty, "Hard Stop Loss (-0.8%)")
            elif take_profit:
                Execute_Order(symbol, OrderSide.SELL, price, qty, "Take Profit Target (+1.5%)")
            elif buy_signal:
                Execute_Order(symbol, OrderSide.BUY, price, target_qty, "VWAP + Fast EMA Crossover Trigger")
            elif sell_signal:
                Execute_Order(symbol, OrderSide.SELL, price, qty, "Trend Breakdown Exit")

    st.dataframe(pd.DataFrame(scan_matrix), use_container_width=True)

# --- TAB 3: AUDIT LOGS ---
with tab_logs:
    st.subheader("Live Execution Log")
    if st.session_state.audit_log:
        st.dataframe(pd.DataFrame(st.session_state.audit_log), use_container_width=True)
    else:
        st.info("No trade activity logged in current session.")
