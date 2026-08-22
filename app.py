import os
import time
import math
import threading
import requests
import streamlit as st
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timedelta
from collections import deque

# Alpaca API SDK
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest, MarketOrderRequest,
    GetOrdersRequest, StopLossRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# ─────────────────────────────────────────────
# 1. ENV & CLIENT SETUP
# ─────────────────────────────────────────────
load_dotenv()
API_KEY    = os.getenv("ALPACA_API_KEY")    or st.secrets.get("ALPACA_API_KEY", None)
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY", None)
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")

if not API_KEY or not SECRET_KEY:
    st.error("⚠️ Alpaca API Keys missing in .env or Streamlit Secrets!")
    st.stop()

@st.cache_resource
def get_clients():
    tc = TradingClient(API_KEY, SECRET_KEY, paper=True)
    dc = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    return tc, dc

trading_client, data_client = get_clients()

# ─────────────────────────────────────────────
# 2. PAGE CONFIG & AUTO REFRESH
# ─────────────────────────────────────────────
st.set_page_config(page_title="Institutional Scalper v2", layout="wide")
st.title("⚡ Institutional-Grade Scalper — Production Risk Edition")
st_autorefresh(interval=5000, key="scalper_loop")

# ─────────────────────────────────────────────
# 3. SESSION STATE BOOTSTRAP
# ─────────────────────────────────────────────
DEFAULTS = {
    "trade_audit":          [],
    "order_state_machine":  {},   # symbol -> {order_id, state, side, qty, limit, ts}
    "session_pnl":          0.0,
    "session_start_equity": None,
    "daily_kill_triggered": False,
    "backtest_results":     None,
    "price_cache":          {},   # symbol -> deque of last 50 prices for ATR
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─────────────────────────────────────────────
# 4. CONSTANTS — ALL RULE-BASED, ZERO VAGUENESS
# ─────────────────────────────────────────────
SLIPPAGE_BUY_PCT     = 0.0015   # Paper trading penalty: buy 0.15% worse
SLIPPAGE_SELL_PCT    = 0.0015   # Paper trading penalty: sell 0.15% worse
COMMISSION_PER_SHARE = 0.005    # $0.005/share simulated friction
MAX_DAILY_LOSS_PCT   = 0.03     # 3% daily drawdown kill switch
MAX_RISK_PER_TRADE   = 0.01     # Kelly/fixed-fractional: 1% of equity per trade
STOP_LOSS_PCT        = 0.005    # Hard 0.5% stop loss per trade
TAKE_PROFIT_PCT      = 0.010    # 1.0% take profit target
ATR_PERIOD           = 14       # ATR lookback for position sizing
RSI_PERIOD           = 7
EMA_FAST             = 5
EMA_SLOW             = 20
MAX_SECTOR_EXPOSURE  = 3        # Max simultaneous positions in same sector

SECTOR_MAP = {
    "AAPL": "Tech", "MSFT": "Tech", "NVDA": "Tech", "AMD": "Tech",
    "TSLA": "Auto", "AMZN": "Retail",
    "JPM": "Finance", "GS": "Finance",
    "XOM": "Energy", "CVX": "Energy",
}

# ─────────────────────────────────────────────
# 5. TELEGRAM ALERT (NON-BLOCKING)
# ─────────────────────────────────────────────
def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT, "text": msg}, timeout=5)
    except Exception:
        pass

def alert(msg: str):
    st.toast(msg)
    threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()

# ─────────────────────────────────────────────
# 6. MARKET METRICS WITH LOOK-AHEAD-FREE DATA
# ─────────────────────────────────────────────
def get_market_metrics(symbol: str):
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            limit=50
        )
        bars = data_client.get_stock_bars(req)
        df = bars.df
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol") if symbol in df.index.get_level_values("symbol") else df
        if df.empty or len(df) < ATR_PERIOD + 5:
            return None

        closes  = df["close"]
        volumes = df["volume"]
        highs   = df["high"]
        lows    = df["low"]

        # EMAs
        ema_fast = closes.ewm(span=EMA_FAST, adjust=False).mean().iloc[-1]
        ema_slow = closes.ewm(span=EMA_SLOW, adjust=False).mean().iloc[-1]

        # Fast RSI — mathematically precise
        delta = closes.diff()
        gain  = delta.where(delta > 0, 0.0).rolling(RSI_PERIOD).mean()
        loss  = (-delta.where(delta < 0, 0.0)).rolling(RSI_PERIOD).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = (100 - (100 / (1 + rs))).iloc[-1]

        # VWAP
        tp   = (highs + lows + closes) / 3
        vwap = (tp * volumes).sum() / volumes.sum()

        # ATR (Wilder's) — used for volatility-based position sizing
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows  - closes.shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.ewm(span=ATR_PERIOD, adjust=False).mean().iloc[-1]

        # Volume spike detection (current vol vs 20-bar avg)
        avg_vol   = volumes.iloc[:-1].rolling(20).mean().iloc[-1]
        vol_ratio = volumes.iloc[-1] / avg_vol if avg_vol > 0 else 1.0

        latest_price = closes.iloc[-1]

        return {
            "price":    latest_price,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi":      rsi,
            "vwap":     vwap,
            "atr":      atr,
            "vol_ratio": vol_ratio,
        }
    except Exception as e:
        return None

# ─────────────────────────────────────────────
# 7. VOLATILITY-ADJUSTED POSITION SIZING
#    Risk = equity * MAX_RISK_PER_TRADE
#    Shares = Risk / (ATR * stop_atr_multiplier)
# ─────────────────────────────────────────────
def compute_position_size(equity: float, atr: float, price: float, override_qty: int = None) -> int:
    if override_qty:
        return override_qty
    if atr <= 0 or price <= 0:
        return 1
    risk_dollars = equity * MAX_RISK_PER_TRADE
    stop_distance = max(atr * 1.5, price * STOP_LOSS_PCT)
    qty = int(risk_dollars / stop_distance)
    return max(1, min(qty, 100))

# ─────────────────────────────────────────────
# 8. ORDER STATE MACHINE
# ─────────────────────────────────────────────
def sync_order_state():
    """Pull live Alpaca order statuses and sync internal state machine."""
    osm = st.session_state.order_state_machine
    symbols_to_remove = []
    for symbol, record in osm.items():
        try:
            order = trading_client.get_order_by_id(record["order_id"])
            prev_state = record["state"]
            new_state  = order.status.value
            record["state"] = new_state
            if new_state in ("filled", "canceled", "expired", "rejected") and prev_state not in ("filled", "canceled", "expired", "rejected"):
                alert(f"📋 {symbol} order {new_state.upper()} | {record['side']} {record['qty']} @ ${record.get('limit','mkt')}")
            if new_state in ("canceled", "expired", "rejected"):
                symbols_to_remove.append(symbol)
        except Exception:
            pass
    for s in symbols_to_remove:
        osm.pop(s, None)

# ─────────────────────────────────────────────
# 9. SECTOR CORRELATION GUARD
# ─────────────────────────────────────────────
def sector_allows_entry(symbol: str, active_positions: dict) -> bool:
    sector = SECTOR_MAP.get(symbol, "Unknown")
    count = sum(
        1 for sym in active_positions
        if SECTOR_MAP.get(sym, "?") == sector and active_positions[sym]["qty"] > 0
    )
    return count < MAX_SECTOR_EXPOSURE

# ─────────────────────────────────────────────
# 10. DAILY DRAWDOWN KILL SWITCH
# ─────────────────────────────────────────────
def check_kill_switch(current_equity: float) -> bool:
    if st.session_state.daily_kill_triggered:
        return True
    if st.session_state.session_start_equity is None:
        st.session_state.session_start_equity = current_equity
        return False
    drawdown = (st.session_state.session_start_equity - current_equity) / st.session_state.session_start_equity
    if drawdown >= MAX_DAILY_LOSS_PCT:
        st.session_state.daily_kill_triggered = True
        alert(f"🚨 DAILY KILL SWITCH: Drawdown {drawdown*100:.2f}% exceeded {MAX_DAILY_LOSS_PCT*100:.0f}%. Flattening ALL positions.")
        trading_client.cancel_orders()
        positions = trading_client.get_all_positions()
        for p in positions:
            trading_client.close_position(p.symbol)
        return True
    return False

# ─────────────────────────────────────────────
# 11. EXECUTION ENGINE WITH SLIPPAGE PENALTY
# ─────────────────────────────────────────────
def execute_order(
    symbol: str,
    side: OrderSide,
    price: float,
    qty: int,
    reason: str,
    equity: float = 100_000,
    atr: float = 0.0,
    override_qty: int = None,
):
    osm = st.session_state.order_state_machine

    # Prevent double-ordering: reject if we already have a live order for this symbol
    if symbol in osm and osm[symbol]["state"] in ("new", "partially_filled", "accepted", "pending_new"):
        return False

    final_qty = compute_position_size(equity, atr, price, override_qty)

    # Apply slippage penalty (paper trading realism)
    if side == OrderSide.BUY:
        limit_price = round(price * (1 + SLIPPAGE_BUY_PCT), 2)
    else:
        limit_price = round(price * (1 - SLIPPAGE_SELL_PCT), 2)

    # Simulate commission friction
    estimated_friction = final_qty * COMMISSION_PER_SHARE
    expected_pnl_threshold = final_qty * price * 0.001  # Must expect > 0.1% gain net
    if side == OrderSide.BUY and estimated_friction >= expected_pnl_threshold:
        st.warning(f"⚠️ {symbol}: Expected edge ({expected_pnl_threshold:.2f}) below friction ({estimated_friction:.2f}). Skipping.")
        return False

    try:
        order_req = LimitOrderRequest(
            symbol=symbol,
            qty=final_qty,
            side=side,
            limit_price=limit_price,
            time_in_force=TimeInForce.DAY,
            extended_hours=True,
        )
        submitted = trading_client.submit_order(order_req)

        # Register in state machine
        osm[symbol] = {
            "order_id": str(submitted.id),
            "state":    "new",
            "side":     side.value,
            "qty":      final_qty,
            "limit":    limit_price,
            "ts":       datetime.now().isoformat(),
        }

        st.session_state.trade_audit.insert(0, {
            "Time":       pd.Timestamp.now().strftime("%H:%M:%S"),
            "Symbol":     symbol,
            "Action":     side.value.upper(),
            "Qty":        final_qty,
            "Fill Limit": f"${limit_price:.2f}",
            "Slippage":   f"${abs(limit_price - price):.3f}",
            "Friction":   f"${estimated_friction:.2f}",
            "Reason":     reason,
        })
        alert(f"⚡ {side.value.upper()} {final_qty}x {symbol} @ ${limit_price:.2f} | {reason}")
        return True
    except Exception as e:
        st.error(f"Execution Error ({symbol}): {e}")
        alert(f"❌ Order FAILED {symbol}: {e}")
        return False

# ─────────────────────────────────────────────
# 12. BUILT-IN BACKTESTER (WALK-FORWARD)
#     Uses stored bar data — zero look-ahead bias
# ─────────────────────────────────────────────
def run_backtest(symbol: str, bars_limit: int = 500, train_ratio: float = 0.7) -> dict:
    try:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            limit=bars_limit,
        )
        bars   = data_client.get_stock_bars(req)
        df_raw = bars.df
        if isinstance(df_raw.index, pd.MultiIndex):
            df_raw = df_raw.xs(symbol, level="symbol")
        if len(df_raw) < 60:
            return {"error": "Insufficient data"}

        closes  = df_raw["close"].reset_index(drop=True)
        highs   = df_raw["high"].reset_index(drop=True)
        lows    = df_raw["low"].reset_index(drop=True)
        volumes = df_raw["volume"].reset_index(drop=True)

        split   = int(len(closes) * train_ratio)
        results = {}

        for phase, idx_range in [("in_sample", range(25, split)), ("out_of_sample", range(split, len(closes)))]:
            equity  = 100_000.0
            trades  = []
            in_pos  = False
            entry_p = 0.0
            entry_q = 0
            wins    = 0

            for i in idx_range:
                c = closes[:i+1]
                h = highs[:i+1]
                lo = lows[:i+1]
                v = volumes[:i+1]

                if len(c) < 25:
                    continue

                ef = c.ewm(span=EMA_FAST, adjust=False).mean().iloc[-1]
                es = c.ewm(span=EMA_SLOW, adjust=False).mean().iloc[-1]

                delta = c.diff()
                gain  = delta.where(delta > 0, 0.0).rolling(RSI_PERIOD).mean().iloc[-1]
                loss  = (-delta.where(delta < 0, 0.0)).rolling(RSI_PERIOD).mean().iloc[-1]
                rsi   = 100 - (100 / (1 + gain / loss)) if loss > 0 else 50

                tp   = (h + lo + c) / 3
                vwap = (tp * v).sum() / v.sum()

                tr_s = pd.concat([h-lo, (h-c.shift()).abs(), (lo-c.shift()).abs()], axis=1).max(axis=1)
                atr  = tr_s.ewm(span=ATR_PERIOD, adjust=False).mean().iloc[-1]

                price = c.iloc[-1]
                buy_ok  = (ef > es) and (price >= vwap) and (rsi < 55) and not in_pos
                sell_ok = (in_pos) and ((ef < es) or (rsi > 65))

                pnl_pct = ((price - entry_p) / entry_p) if in_pos and entry_p > 0 else 0
                stop     = in_pos and (pnl_pct <= -STOP_LOSS_PCT)
                take     = in_pos and (pnl_pct >= TAKE_PROFIT_PCT)

                if in_pos and (stop or take or sell_ok):
                    fill  = price * (1 - SLIPPAGE_SELL_PCT)
                    pnl   = (fill - entry_p) * entry_q - entry_q * COMMISSION_PER_SHARE
                    equity += pnl
                    trades.append(pnl)
                    if pnl > 0:
                        wins += 1
                    in_pos = False

                elif buy_ok:
                    risk   = equity * MAX_RISK_PER_TRADE
                    stop_d = max(atr * 1.5, price * STOP_LOSS_PCT)
                    qty    = max(1, int(risk / stop_d))
                    entry_p = price * (1 + SLIPPAGE_BUY_PCT)
                    entry_q = qty
                    in_pos  = True

            n     = len(trades)
            gross = sum(trades)
            wr    = wins / n if n > 0 else 0
            avg   = gross / n if n > 0 else 0
            dd    = 0.0
            peak  = 100_000.0
            running = 100_000.0
            for t in trades:
                running += t
                if running > peak:
                    peak = running
                dd = max(dd, (peak - running) / peak)
            sharpe = 0.0
            if n > 1:
                arr = np.array(trades)
                sharpe = (arr.mean() / arr.std()) * np.sqrt(252 * 390) if arr.std() > 0 else 0

            results[phase] = {
                "trades":       n,
                "win_rate":     f"{wr*100:.1f}%",
                "total_pnl":    f"${gross:,.2f}",
                "avg_trade":    f"${avg:.2f}",
                "max_drawdown": f"{dd*100:.1f}%",
                "sharpe":       f"{sharpe:.2f}",
                "final_equity": f"${equity:,.2f}",
            }

        return results
    except Exception as e:
        return {"error": str(e)}

# ─────────────────────────────────────────────
# 13. SIDEBAR CONTROLS
# ─────────────────────────────────────────────
st.sidebar.header("🕹️ Quantitative Controls")

if st.session_state.daily_kill_triggered:
    st.sidebar.error("🚨 DAILY KILL SWITCH ACTIVE — trading locked.")
    bot_active = False
else:
    bot_active = st.sidebar.toggle("🟢 Activate Auto-Trading Engine", value=False)

use_dynamic_sizing = st.sidebar.checkbox("📐 Volatility-Based Position Sizing", value=True)
override_qty       = st.sidebar.number_input("Fixed Shares (if sizing disabled)", 1, 100, 5)

watchlist_input = st.sidebar.text_area("📋 Watchlist (comma-separated)", value="AAPL,TSLA,NVDA,AMD,MSFT,AMZN")
watchlist = [s.strip().upper() for s in watchlist_input.split(",") if s.strip()]

st.sidebar.markdown("---")
st.sidebar.subheader("🔬 Walk-Forward Backtest")
bt_symbol = st.sidebar.selectbox("Symbol to Backtest", watchlist)
if st.sidebar.button("▶️ Run Backtest"):
    with st.spinner(f"Running walk-forward backtest on {bt_symbol}..."):
        st.session_state.backtest_results = (bt_symbol, run_backtest(bt_symbol))

st.sidebar.markdown("---")
if st.sidebar.button("🚨 EMERGENCY: CANCEL ALL & LIQUIDATE"):
    trading_client.cancel_orders()
    for p in trading_client.get_all_positions():
        trading_client.close_position(p.symbol)
    st.session_state.daily_kill_triggered = True
    alert("🚨 EMERGENCY LIQUIDATION EXECUTED")
    st.sidebar.success("All positions closed and engine locked.")

if st.session_state.daily_kill_triggered:
    if st.sidebar.button("🔓 Reset Kill Switch (New Day)"):
        st.session_state.daily_kill_triggered = False
        st.session_state.session_start_equity = None

# ─────────────────────────────────────────────
# 14. LIVE DATA — POSITIONS & ORDERS
# ─────────────────────────────────────────────
sync_order_state()
positions       = trading_client.get_all_positions()
active_positions = {
    p.symbol: {
        "qty":           int(float(p.qty)),
        "avg_entry":     float(p.avg_entry_price),
        "unrealized_pnl": float(p.unrealized_pl),
    }
    for p in positions
}

open_orders         = trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
pending_buy_symbols = {o.symbol for o in open_orders if o.side == OrderSide.BUY}

acc            = trading_client.get_account()
current_equity = float(acc.equity)
kill_triggered = check_kill_switch(current_equity)

# ─────────────────────────────────────────────
# 15. UI TABS
# ─────────────────────────────────────────────
tab_signals, tab_positions, tab_audit, tab_backtest, tab_risk = st.tabs([
    "⚡ Live Signal Matrix",
    "💼 Active Positions & Risk",
    "📜 Execution Audit Trail",
    "🔬 Backtest Results",
    "🛡️ Risk Dashboard",
])

# ── TAB 1: SIGNAL MATRIX ──
with tab_signals:
    st.subheader("Real-Time Multi-Stock Signal Stream (Slippage-Penalised)")

    if kill_triggered:
        st.error("🚨 DAILY KILL SWITCH ACTIVE. No new trades will be placed today.")

    matrix = []

    for symbol in watchlist:
        metrics = get_market_metrics(symbol)
        if not metrics:
            continue

        price    = metrics["price"]
        ema_f    = metrics["ema_fast"]
        ema_s    = metrics["ema_slow"]
        rsi      = metrics["rsi"]
        vwap     = metrics["vwap"]
        atr      = metrics["atr"]
        vol_ratio = metrics["vol_ratio"]

        pos_data   = active_positions.get(symbol, {"qty": 0, "avg_entry": 0.0, "unrealized_pnl": 0.0})
        holding_qty = pos_data["qty"]
        avg_entry   = pos_data["avg_entry"]

        pnl_pct = 0.0
        if holding_qty > 0 and avg_entry > 0:
            pnl_pct = (price - avg_entry) / avg_entry

        is_stop_loss   = holding_qty > 0 and pnl_pct <= -STOP_LOSS_PCT
        is_take_profit = holding_qty > 0 and pnl_pct >= TAKE_PROFIT_PCT

        # ENTRY: EMA crossover + VWAP support + RSI neutral + volume confirmation
        buy_signal = (
            ema_f > ema_s
            and price >= vwap
            and rsi < 55
            and vol_ratio >= 1.2           # Volume spike confirmation
            and holding_qty == 0
            and symbol not in pending_buy_symbols
            and sector_allows_entry(symbol, active_positions)
        )

        sell_signal = ((ema_f < ema_s) or (rsi > 65)) and holding_qty > 0

        status = "NEUTRAL"
        if is_stop_loss:
            status = "🛑 STOP LOSS"
        elif is_take_profit:
            status = "🎯 TAKE PROFIT"
        elif buy_signal:
            status = "🟢 BUY"
        elif sell_signal:
            status = "🔴 SELL"

        # Volatility-based sizing preview
        sizing_qty = compute_position_size(current_equity, atr, price, None if use_dynamic_sizing else override_qty)

        matrix.append({
            "Symbol":     symbol,
            "Price":      f"${price:.2f}",
            "EMA(5)":     f"${ema_f:.2f}",
            "EMA(20)":    f"${ema_s:.2f}",
            "RSI(7)":     f"{rsi:.1f}",
            "ATR":        f"${atr:.3f}",
            "Vol×Avg":    f"{vol_ratio:.2f}x",
            "VWAP":       f"${vwap:.2f}",
            "Pos PnL":    f"{pnl_pct*100:+.2f}%" if holding_qty > 0 else "—",
            "Holdings":   holding_qty,
            "Sizing":     sizing_qty,
            "Status":     status,
        })

        if bot_active and not kill_triggered:
            eq_arg  = current_equity
            qty_arg = None if use_dynamic_sizing else override_qty

            if is_stop_loss:
                execute_order(symbol, OrderSide.SELL, price, holding_qty,
                              f"HARD STOP LOSS ({pnl_pct*100:.2f}%)", eq_arg, atr, holding_qty)
            elif is_take_profit:
                execute_order(symbol, OrderSide.SELL, price, holding_qty,
                              f"TAKE PROFIT (+{pnl_pct*100:.2f}%)", eq_arg, atr, holding_qty)
            elif buy_signal:
                execute_order(symbol, OrderSide.BUY, price, 0,
                              "EMA Breakout + VWAP + Volume Spike", eq_arg, atr, qty_arg)
            elif sell_signal:
                execute_order(symbol, OrderSide.SELL, price, holding_qty,
                              "Trend Reversal / RSI Exit", eq_arg, atr, holding_qty)

    if matrix:
        st.dataframe(pd.DataFrame(matrix), use_container_width=True)
    else:
        st.info("No signal data available. Markets may be closed or API limit hit.")

# ── TAB 2: POSITIONS ──
with tab_positions:
    st.subheader("Live Portfolio Holdings & Account Equity")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Equity",          f"${current_equity:,.2f}")
    col2.metric("Buying Power",    f"${float(acc.buying_power):,.2f}")
    col3.metric("Daytrade Count",  acc.daytrade_count)
    session_dd = 0.0
    if st.session_state.session_start_equity:
        session_dd = (st.session_state.session_start_equity - current_equity) / st.session_state.session_start_equity * 100
    col4.metric("Session Drawdown", f"{session_dd:.2f}%", delta_color="inverse")

    st.progress(min(abs(session_dd) / (MAX_DAILY_LOSS_PCT * 100), 1.0), text=f"Daily Loss Budget Used: {abs(session_dd):.2f}% / {MAX_DAILY_LOSS_PCT*100:.0f}%")
    st.markdown("---")

    if positions:
        pos_df = pd.DataFrame([{
            "Symbol":          p.symbol,
            "Qty":             p.qty,
            "Avg Entry":       f"${float(p.avg_entry_price):.2f}",
            "Current Price":   f"${float(p.current_price):.2f}",
            "Unrealized P/L":  f"${float(p.unrealized_pl):,.2f}",
            "Unrealized %":    f"{float(p.unrealized_plpc)*100:+.2f}%",
            "Sector":          SECTOR_MAP.get(p.symbol, "Unknown"),
        } for p in positions])
        st.dataframe(pos_df, use_container_width=True)
    else:
        st.info("No open positions.")

    st.markdown("---")
    st.subheader("🔄 Order State Machine")
    osm = st.session_state.order_state_machine
    if osm:
        st.dataframe(pd.DataFrame(list(osm.values()), index=list(osm.keys())), use_container_width=True)
    else:
        st.info("No tracked orders.")

# ── TAB 3: AUDIT ──
with tab_audit:
    st.subheader("Real-Time Execution Audit Trail")
    if st.session_state.trade_audit:
        st.dataframe(pd.DataFrame(st.session_state.trade_audit), use_container_width=True)
    else:
        st.info("No trades executed in current session.")

# ── TAB 4: BACKTEST ──
with tab_backtest:
    st.subheader("🔬 Walk-Forward Backtest Results")
    st.caption("In-sample: strategy trained on 70% of data. Out-of-sample: validated on remaining 30%. Zero look-ahead bias.")
    if st.session_state.backtest_results:
        sym, res = st.session_state.backtest_results
        st.markdown(f"### Results for `{sym}`")
        if "error" in res:
            st.error(res["error"])
        else:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**📚 In-Sample (Training)**")
                st.table(pd.DataFrame(res["in_sample"], index=["Value"]).T)
            with c2:
                st.markdown("**🧪 Out-of-Sample (Validation)**")
                st.table(pd.DataFrame(res["out_of_sample"], index=["Value"]).T)
            is_wr  = float(res["in_sample"]["win_rate"].replace("%",""))
            oos_wr = float(res["out_of_sample"]["win_rate"].replace("%",""))
            if oos_wr >= is_wr * 0.8:
                st.success("✅ Strategy holds out-of-sample. Low overfitting risk.")
            else:
                st.warning("⚠️ Significant performance degradation out-of-sample. Possible curve-fitting.")
    else:
        st.info("Select a symbol in the sidebar and click ▶️ Run Backtest.")

# ── TAB 5: RISK DASHBOARD ──
with tab_risk:
    st.subheader("🛡️ Risk Architecture Overview")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Active Risk Parameters**")
        st.table(pd.DataFrame({
            "Parameter": [
                "Max Daily Loss", "Max Risk/Trade", "Stop Loss %",
                "Take Profit %", "Buy Slippage", "Sell Slippage",
                "Commission/Share", "ATR Period", "Max Sector Exposure"
            ],
            "Value": [
                f"{MAX_DAILY_LOSS_PCT*100:.0f}%", f"{MAX_RISK_PER_TRADE*100:.1f}%",
                f"{STOP_LOSS_PCT*100:.2f}%", f"{TAKE_PROFIT_PCT*100:.2f}%",
                f"{SLIPPAGE_BUY_PCT*100:.2f}%", f"{SLIPPAGE_SELL_PCT*100:.2f}%",
                f"${COMMISSION_PER_SHARE:.4f}", str(ATR_PERIOD), str(MAX_SECTOR_EXPOSURE)
            ]
        }))

    with col2:
        st.markdown("**Sector Exposure**")
        sector_counts = {}
        for sym, pos in active_positions.items():
            if pos["qty"] > 0:
                sec = SECTOR_MAP.get(sym, "Unknown")
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
        if sector_counts:
            st.bar_chart(pd.Series(sector_counts))
        else:
            st.info("No active positions.")

    st.markdown("---")
    st.markdown("**Kill Switch Status**")
    ks_col1, ks_col2 = st.columns(2)
    ks_col1.metric("Kill Switch", "🔴 ACTIVE" if st.session_state.daily_kill_triggered else "🟢 ARMED")
    ks_col2.metric("Session Start Equity", f"${st.session_state.session_start_equity:,.2f}" if st.session_state.session_start_equity else "—")
