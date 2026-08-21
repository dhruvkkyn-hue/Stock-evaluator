import os
import streamlit as st
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

# Alpaca SDK imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# 1. Environment & API Secrets Setup
load_dotenv()

# Streamlit Cloud uses st.secrets; local runs use .env
API_KEY = os.getenv("ALPACA_API_KEY") or st.secrets.get("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    st.error("⚠️ Credentials missing! Set ALPACA_API_KEY and ALPACA_SECRET_KEY in Streamlit Secrets or .env file.")
    st.stop()

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# Page Configuration & Auto-Refresh (High-Frequency 5-second polling)
st.set_page_config(page_title="Institutional Extended-Hours Execution Engine", layout="wide")
st.title("⚡ High-Speed Extended-Hours Execution Engine")
st_autorefresh(interval=5000, key="quant_engine_refresh")

# Initialize Session Logs for Trade Auditing
if "trade_logs" not in st.session_state:
    st.session_state.trade_logs = []

# 2. Institutional Quant & Math Calculations
def Calculate_Quant_Metrics(symbol: str):
    """
    Computes 14-period RSI, 20-period EMA, and VWAP on 1-minute historical data.
    Returns real-time price, metrics, and quantitative bias.
    """
    try:
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            limit=60
        )
        bars = data_client.get_stock_bars(request_params)
        df = bars.df
        
        if df.empty or len(df) < 20:
            return None

        # Extract closing prices and volume
        closes = df['close']
        volumes = df['volume']
        highs = df['high']
        lows = df['low']

        # A. Exponential Moving Average (EMA 20)
        ema20 = closes.ewm(span=20, adjust=False).mean().iloc[-1]

        # B. Volume Weighted Average Price (VWAP)
        typical_price = (highs + lows + closes) / 3
        vwap = (typical_price * volumes).sum() / volumes.sum()

        # C. Relative Strength Index (RSI 14)
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        latest_price = closes.iloc[-1]
        latest_rsi = rsi.iloc[-1]

        return {
            "price": latest_price,
            "rsi": latest_rsi,
            "ema20": ema20,
            "vwap": vwap
        }
    except Exception as e:
        st.error(f"Data Fetch Error ({symbol}): {str(e)}")
        return None

# 3. High-Speed Smart Order Execution System
def Execute_Smart_Trade(symbol: str, side: OrderSide, target_price: float, qty: int, reason: str):
    """
    Validates account equity, applies max sizing risk limits, and submits extended-hours Limit Orders.
    """
    try:
        account = trading_client.get_account()
        equity = float(account.equity)
        buying_power = float(account.buying_power)
        
        order_value = target_price * qty
        
        # Risk Rule 1: Sizing Guard - Max 5% equity allocation per order
        if order_value > (equity * 0.05):
            st.warning(f"⛔ Trade Rejected for {symbol}: Value (${order_value:,.2f}) exceeds 5% max equity guard.")
            return False

        # Risk Rule 2: Buying Power Guard
        if order_value > buying_power:
            st.error(f"⛔ Trade Rejected for {symbol}: Insufficient buying power.")
            return False

        # Enforce Extended Hours Requirements: Limit Order + TimeInForce.DAY
        limit_order_req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=round(target_price, 2),
            time_in_force=TimeInForce.DAY,
            extended_hours=True
        )

        submitted_order = trading_client.submit_order(limit_order_req)
        
        # Log decision for trader audit review
        log_entry = {
            "Time": pd.Timestamp.now().strftime("%H:%M:%S"),
            "Symbol": symbol,
            "Action": side.value.upper(),
            "Qty": qty,
            "Price": f"${target_price:.2f}",
            "Reason": reason
        }
        st.session_state.trade_logs.insert(0, log_entry)
        st.success(f"⚡ ORDER EXECUTED: {side.value.upper()} {qty} shares of {symbol} @ ${target_price:.2f}")
        return True

    except Exception as e:
        st.error(f"❌ Execution Failure: {str(e)}")
        return False

# 4. Streamlit User Interface
st.sidebar.header("🕹️ Strategy Parameters")
auto_mode = st.sidebar.toggle("Activate Automated Signal Bot", value=False)
order_share_qty = st.sidebar.number_input("Shares per Executed Trade", min_value=1, max_value=100, value=5)

watch_list = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT"]

tab_scanner, tab_portfolio, tab_audit = st.tabs(["🎯 Live Signal Scanner", "💼 Positions & Account", "📜 Trade Execution Logs"])

with tab_scanner:
    st.subheader("Quantitative Signal Matrix")
    
    scanner_data = []
    
    for symbol in watch_list:
        metrics = Calculate_Quant_Metrics(symbol)
        
        if metrics:
            price = metrics["price"]
            rsi = metrics["rsi"]
            ema = metrics["ema20"]
            vwap = metrics["vwap"]
            
            # --- PROFIT-FOCUSED TRADING MATHEMATICS ---
            # BUY LOGIC: RSI < 32 (Oversold) AND Price > VWAP (Institutional Upward Bias)
            buy_condition = (rsi <= 32) and (price >= vwap)
            
            # SELL LOGIC: RSI > 68 (Overbought) OR Price below EMA (Trend Breakdown Guard)
            sell_condition = (rsi >= 68) or (price < (ema * 0.995))
            
            status = "NEUTRAL"
            if buy_condition:
                status = "🟢 STRONG BUY"
            elif sell_condition:
                status = "🔴 STRONG SELL"

            scanner_data.append({
                "Symbol": symbol,
                "Price": f"${price:.2f}",
                "RSI (14)": f"{rsi:.1f}",
                "EMA 20": f"${ema:.2f}",
                "VWAP": f"${vwap:.2f}",
                "Signal": status
            })

            # Auto-Trading Execution Loop
            if auto_mode:
                if buy_condition:
                    # Apply 0.1% buffer over market price to ensure fill speed on illiquid books
                    execution_price = price * 1.001
                    reason = f"Quant Trigger: Oversold RSI ({rsi:.1f}) + Bullish VWAP (${vwap:.2f})"
                    Execute_Smart_Trade(symbol, OrderSide.BUY, execution_price, order_share_qty, reason)
                    
                elif sell_condition:
                    execution_price = price * 0.999
                    reason = f"Quant Trigger: Overbought RSI ({rsi:.1f}) or Trend Guard breakdown"
                    Execute_Smart_Trade(symbol, OrderSide.SELL, execution_price, order_share_qty, reason)

    st.table(pd.DataFrame(scanner_data))

with tab_portfolio:
    st.subheader("Account Portfolio Status")
    acc = trading_client.get_account()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Account Equity", f"${float(acc.equity):,.2f}")
    col2.metric("Buying Power", f"${float(acc.buying_power):,.2f}")
    col3.metric("Cash Balance", f"${float(acc.cash):,.2f}")
    
    st.markdown("---")
    st.subheader("Active Positions")
    active_positions = trading_client.get_all_positions()
    if active_positions:
        p_df = pd.DataFrame([{
            "Symbol": p.symbol,
            "Qty": p.qty,
            "Avg Entry": f"${float(p.avg_entry_price):.2f}",
            "Current Price": f"${float(p.current_price):.2f}",
            "Unrealized P/L": f"${float(p.unrealized_pl):,.2f}"
        } for p in active_positions])
        st.dataframe(p_df, use_container_width=True)
    else:
        st.info("No open positions in portfolio.")

with tab_audit:
    st.subheader("Real-Time Execution Audit Trail")
    st.caption("Displays exact quantitative reasons why every trade was executed.")
    if st.session_state.trade_logs:
        st.dataframe(pd.DataFrame(st.session_state.trade_logs), use_container_width=True)
    else:
        st.info("No trades executed in current session.")
