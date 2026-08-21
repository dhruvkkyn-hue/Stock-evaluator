import os
import pandas as pd
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from streamlit_autorefresh import st_autorefresh

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# -------------------------------------------------------------------
# 1. SETUP & INITIALIZATION
# -------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY") or st.secrets.get("ALPACA_API_KEY", None)
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY", None)

if not API_KEY or not SECRET_KEY:
    st.error("⚠️ Credentials missing! Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env or Streamlit Secrets.")
    st.stop()

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

st.set_page_config(page_title="High-Frequency Control Terminal", layout="wide")
st.title("⚡ Low-Latency Quant Engine & Manual Control Terminal")

# Rerun every 2 seconds for high-frequency updates
st_autorefresh(interval=2000, key="quant_terminal_refresh")

if "audit_log" not in st.session_state:
    st.session_state.audit_log = []

TICKER_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
    "NFLX", "INTC", "PYPL", "BAC", "JPM", "DIS", "XOM", "COP", "PFE"
]

MAX_CAPITAL_PER_TRADE = 100.0
SLIPPAGE_PENALTY_PCT = 0.0005

# -------------------------------------------------------------------
# 2. FAST PORTFOLIO & ORDER STATE SYNC
# -------------------------------------------------------------------
def Get_Live_Portfolio():
    try:
        account = trading_client.get_account()
        positions_raw = trading_client.get_all_positions()
        pos_map = {
            p.symbol: {
                "qty": int(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "price": float(p.current_price),
                "market_val": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "pnl_pct": float(p.unrealized_plpc)
            } for p in positions_raw
        }
        return account, pos_map, positions_raw
    except Exception as e:
        st.error(f"Portfolio Sync Error: {e}")
        return None, {}, []

# -------------------------------------------------------------------
# 3. ADVANCED ALPHA SIGNAL ENGINE (VWAP + ADX + ATR EDGE)
# -------------------------------------------------------------------
def Compute_Statistical_Edge(symbol: str):
    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            limit=35
        )
        bars = data_client.get_stock_bars(request)
        df = bars.df
        if df.empty or len(df) < 25:
            return None

        # VWAP
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        vwap = df['pv'].sum() / df['volume'].sum() if df['volume'].sum() > 0 else df['close'].iloc[-1]
        
        latest_price = df['close'].iloc[-1]
        ema_fast = df['close'].ewm(span=5, adjust=False).mean().iloc[-1]
        ema_slow = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]

        # True Range & ATR
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift()).abs(),
            (df['low'] - df['close'].shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        # Directional Movement for Trend Strength (ADX Proxy)
        up_move = df['high'].diff()
        down_move = -df['low'].diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        tr_smooth = tr.rolling(14).sum().iloc[-1]
        plus_di = 100 * (pd.Series(plus_dm).rolling(14).sum().iloc[-1] / tr_smooth) if tr_smooth > 0 else 0
        minus_di = 100 * (pd.Series(minus_dm).rolling(14).sum().iloc[-1] / tr_smooth) if tr_smooth > 0 else 0
        
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-6)) * 100

        return {
            "Symbol": symbol,
            "Price": latest_price,
            "VWAP": vwap,
            "EMA_Fast": ema_fast,
            "EMA_Slow": ema_slow,
            "ATR": atr,
            "Trend_Strength": dx,
            "Bullish_Bias": plus_di > minus_di
        }
    except Exception:
        return None

def Parallel_Universe_Scan(universe):
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(universe), 12)) as executor:
        out = executor.map(Compute_Statistical_Edge, universe)
        for res in out:
            if res:
                results[res["Symbol"]] = res
    return results

# -------------------------------------------------------------------
# 4. ORDER ROUTER & MANUAL EXECUTION CONTROLLER
# -------------------------------------------------------------------
def Send_Order(symbol: str, side: OrderSide, price: float, qty: int, reason: str):
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
            "Type": "AUTOBOT" if "Manual" not in reason else "MANUAL",
            "Reason": reason
        })
        st.toast(f"⚡ ORDER EXECUTED: {side.value.upper()} {qty} {symbol} @ ${limit_price:.2f}")
    except Exception as e:
        st.error(f"Execution Error ({symbol}): {str(e)}")

# -------------------------------------------------------------------
# 5. DASHBOARD LAYOUT & CONTROLS
# -------------------------------------------------------------------
account, active_pos_map, raw_positions = Get_Live_Portfolio()

# Sidebar Control Station
st.sidebar.header("🕹️ Execution Controls")
bot_active = st.sidebar.toggle("🟢 Activate Autonomous Trading Engine", value=False)

if account:
    st.sidebar.metric("Portfolio Equity", f"${float(account.equity):,.2f}")
    st.sidebar.metric("Buying Power", f"${float(account.buying_power):,.2f}")

st.sidebar.markdown("---")
st.sidebar.subheader("🚨 Emergency Overrides")

if st.sidebar.button("💥 CANCEL ALL PENDING ORDERS"):
    trading_client.cancel_orders()
    st.sidebar.success("All pending orders canceled.")

if st.sidebar.button("🔥 PANIC LIQUIDATE ENTIRE PORTFOLIO"):
    trading_client.cancel_orders()
    for sym, pos in active_pos_map.items():
        if pos["qty"] > 0:
            trading_client.close_position(sym)
    st.sidebar.warning("Liquidated all active positions.")

# Tabs
tab_terminal, tab_manual, tab_signals, tab_audit = st.tabs([
    "💼 Portfolio & Direct Controls", 
    "🎯 Quick Manual Trade", 
    "⚡ High-Edge Signal Scanner", 
    "📜 Audit Log"
])

# --- TAB 1: ACTIVE PORTFOLIO & ONE-CLICK MANUAL SELLING ---
with tab_terminal:
    st.subheader("Active Holdings & One-Click Order Triggers")
    if raw_positions:
        for p in raw_positions:
            col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 3])
            col1.write(f"**{p.symbol}** ({p.qty} shrs)")
            col2.write(f"Entry: **${float(p.avg_entry_price):.2f}**")
            col3.write(f"Current: **${float(p.current_price):.2f}**")
            
            pnl_val = float(p.unrealized_pl)
            col4.markdown(f":{'green' if pnl_val >= 0 else 'red'}[**${pnl_val:+.2f} ({float(p.unrealized_plpc)*100:+.2f}%)**]")
            
            # Interactive Action Buttons per stock
            with col5:
                btn_buy, btn_sell = st.columns(2)
                if btn_buy.button("➕ Buy +1", key=f"buy_more_{p.symbol}"):
                    Send_Order(p.symbol, OrderSide.BUY, float(p.current_price), 1, "Manual Position Top-Up")
                if btn_sell.button("❌ Close", key=f"close_{p.symbol}"):
                    trading_client.close_position(p.symbol)
                    st.toast(f"Liquidated position in {p.symbol}")
            st.divider()
    else:
        st.info("No open positions in portfolio.")

# --- TAB 2: MANUAL TRADE CONSOLE ---
with tab_manual:
    st.subheader("Manual Execution Terminal")
    c1, c2, c3, c4 = st.columns(4)
    manual_symbol = c1.selectbox("Select Ticker", TICKER_UNIVERSE)
    manual_action = c2.radio("Order Side", ["BUY", "SELL"])
    manual_qty = c3.number_input("Shares Quantity", min_value=1, max_value=100, value=1)
    
    # Fetch current price for manual reference
    snap = Compute_Statistical_Edge(manual_symbol)
    ref_price = snap["Price"] if snap else 0.0
    c4.metric("Live Reference Price", f"${ref_price:.2f}")

    if st.button("🚀 SUBMIT MANUAL ORDER", use_container_width=True):
        if ref_price > 0:
            side = OrderSide.BUY if manual_action == "BUY" else OrderSide.SELL
            Send_Order(manual_symbol, side, ref_price, manual_qty, f"Manual User Action ({manual_action})")
        else:
            st.error("Could not verify live price.")

# --- TAB 3: PARALLEL MARKET SCANNER ---
with tab_signals:
    st.subheader("Institutional Multi-Factor Scanner")
    snapshot = Parallel_Universe_Scan(TICKER_UNIVERSE)
    
    open_orders = trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
    pending_symbols = [o.symbol for o in open_orders]

    scan_matrix = []
    
    for symbol, data in snapshot.items():
        price = data["Price"]
        vwap = data["VWAP"]
        ema_f = data["EMA_Fast"]
        ema_s = data["EMA_Slow"]
        dx = data["Trend_Strength"]
        bullish = data["Bullish_Bias"]

        pos_info = active_pos_map.get(symbol, {"qty": 0, "pnl_pct": 0.0})
        qty = pos_info["qty"]
        pnl_pct = pos_info["pnl_pct"]

        target_qty = int(MAX_CAPITAL_PER_TRADE // price)

        # Risk Triggers
        stop_loss = (qty > 0) and (pnl_pct <= -0.008)
        take_profit = (qty > 0) and (pnl_pct >= 0.015)

        # High-Edge Quantitative Signal (VWAP Support + Fast EMA + High ADX Trend Strength)
        buy_signal = (
            (price > vwap) and 
            (ema_f > ema_s) and 
            (bullish) and 
            (dx > 20.0) and 
            (qty == 0) and 
            (target_qty >= 1) and 
            (symbol not in pending_symbols)
        )
        
        sell_signal = ((ema_f < ema_s) or (price < vwap)) and (qty > 0)

        status = "NEUTRAL"
        if stop_loss:
            status = "🛑 STOP LOSS"
        elif take_profit:
            status = "🎯 TAKE PROFIT"
        elif buy_signal:
            status = f"🟢 STRONG BUY ({target_qty} shrs)"
        elif sell_signal:
            status = "🔴 EXIT SIGNAL"

        scan_matrix.append({
            "Symbol": symbol,
            "Price": f"${price:.2f}",
            "VWAP": f"${vwap:.2f}",
            "EMA (5/20)": f"${ema_f:.2f} / ${ema_s:.2f}",
            "Trend Strength (ADX)": f"{dx:.1f}",
            "Position": qty,
            "PnL (%)": f"{pnl_pct*100:+.2f}%" if qty > 0 else "0.00%",
            "Signal": status
        })

        # AUTOMATED EXECUTION ENGINE
        if bot_active:
            if stop_loss:
                Send_Order(symbol, OrderSide.SELL, price, qty, "Auto Stop-Loss (-0.8%)")
            elif take_profit:
                Send_Order(symbol, OrderSide.SELL, price, qty, "Auto Take-Profit (+1.5%)")
            elif buy_signal:
                Send_Order(symbol, OrderSide.BUY, price, target_qty, "Auto Alpha Buy (VWAP + High ADX)")
            elif sell_signal:
                Send_Order(symbol, OrderSide.SELL, price, qty, "Auto Exit Signal (Trend Break)")

    st.dataframe(pd.DataFrame(scan_matrix), use_container_width=True)

# --- TAB 4: AUDIT LOGS ---
with tab_audit:
    st.subheader("Order & Execution Audit Log")
    if st.session_state.audit_log:
        st.dataframe(pd.DataFrame(st.session_state.audit_log), use_container_width=True)
    else:
        st.info("No trade activity logged in this session.")
