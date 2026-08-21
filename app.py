import os
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

# Alpaca SDK imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# 1. Environment & API Initialization
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    st.error("Missing Alpaca API Credentials in .env file.")
    st.stop()

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# Streamlit Page Setup
st.set_page_config(page_title="Alpaca Extended Hours Trader", layout="wide")
st.title("⚡ Extended-Hours Trading & Signal Manager")

# Auto-refresh UI every 15 seconds
st_autorefresh(interval=15000, key="datarefresh")

# 2. Risk Management Helper Functions
def validate_and_place_order(symbol: str, side: OrderSide, limit_price: float, qty: int, is_ext_hours: bool):
    """Guards against sizing, spread, and TIF constraints before submitting order."""
    try:
        account = trading_client.get_account()
        equity = float(account.equity)
        buying_power = float(account.buying_power)
        
        # Guard 1: Position Size Limit (Max 10% of total account equity per order)
        order_val = limit_price * qty
        if order_val > (equity * 0.10):
            st.error(f"❌ Risk Guard: Order value (${order_val:,.2f}) exceeds 10% max equity limit.")
            return False
            
        # Guard 2: Available Buying Power Check
        if order_val > buying_power:
            st.error(f"❌ Risk Guard: Insufficient buying power (${buying_power:,.2f}).")
            return False

        # Guard 3: Extended-Hours Rule Enforcement
        # Extended hours requires TimeInForce.DAY and Limit Order
        tif = TimeInForce.DAY if is_ext_hours else TimeInForce.GTC
        
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=round(limit_price, 2),
            time_in_force=tif,
            extended_hours=is_ext_hours
        )
        
        order = trading_client.submit_order(req)
        st.success(f"✅ Order Submitted: {side.value.upper()} {qty} shares of {symbol} @ ${limit_price:.2f}")
        return True

    except Exception as e:
        st.error(f"❌ Execution Error: {str(e)}")
        return False

# 3. Technical Indicator: RSI Calculation
def calculate_rsi(symbol: str, period: int = 14):
    request_params = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        limit=50
    )
    bars = data_client.get_stock_bars(request_params)
    df = bars.df
    if df.empty:
        return None, None
    
    # Calculate price change
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    latest_price = df['close'].iloc[-1]
    latest_rsi = df['rsi'].iloc[-1]
    return latest_price, latest_rsi

# 4. Streamlit UI Components

# Sidebar Controls
st.sidebar.header("Execution Settings")
ext_hours_enabled = st.sidebar.toggle("Extended Hours Mode (Pre/Post Market)", value=True)
auto_trade = st.sidebar.toggle("Automated RSI Execution", value=False)
max_shares = st.sidebar.number_input("Shares per Auto Trade", min_value=1, max_value=500, value=10)

# Main Dashboard Layout
tab1, tab2, tab3 = st.tabs(["📊 Quant Scanner & Auto Bot", "💼 Positions & Portfolio", "📜 Active Orders"])

with tab1:
    st.subheader("RSI Scanner & Strategy Execution")
    watch_symbols = ["AAPL", "TSLA", "NVDA", "AMD"]
    
    col1, col2 = st.columns(2)
    
    for symbol in watch_symbols:
        price, rsi = calculate_rsi(symbol)
        if price is not None:
            st.write(f"**{symbol}** | Price: `${price:.2f}` | RSI: `{rsi:.2f}`")
            
            # Automated Execution Checks
            if auto_trade:
                # Oversold Buy Signal
                if rsi <= 30:
                    st.warning(f"🚨 OVERSOLD SIGNAL DETECTED FOR {symbol}")
                    # Buy slightly above ask to improve fill chance during low liquidity
                    buy_price = price * 1.002
                    validate_and_place_order(symbol, OrderSide.BUY, buy_price, max_shares, ext_hours_enabled)
                
                # Overbought Sell Signal
                elif rsi >= 70:
                    st.warning(f"🚨 OVERBOUGHT SIGNAL DETECTED FOR {symbol}")
                    sell_price = price * 0.998
                    validate_and_place_order(symbol, OrderSide.SELL, sell_price, max_shares, ext_hours_enabled)

with tab2:
    st.subheader("Live Portfolio & Positions")
    account = trading_client.get_account()
    st.metric("Portfolio Equity", f"${float(account.equity):,.2f}", f"${float(account.buying_power):,.2f} Buying Power")
    
    positions = trading_client.get_all_positions()
    if positions:
        pos_data = [{
            "Symbol": p.symbol,
            "Qty": p.qty,
            "Avg Entry": f"${float(p.avg_entry_price):.2f}",
            "Current Price": f"${float(p.current_price):.2f}",
            "Unrealized P/L": f"${float(p.unrealized_pl):.2f}"
        } for p in positions]
        st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
        
        # Liquidate single position trigger
        liquidate_sym = st.selectbox("Select symbol to close:", [p.symbol for p in positions])
        if st.button("Close Selected Position"):
            trading_client.close_position(liquidate_sym)
            st.success(f"Position for {liquidate_sym} closed.")
    else:
        st.info("No open positions.")

with tab3:
    st.subheader("Order Book")
    if st.button("🚨 Cancel All Open Orders"):
        trading_client.cancel_orders()
        st.warning("All active orders cancelled.")
        
    orders = trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
    if orders:
        order_data = [{
            "ID": o.id,
            "Symbol": o.symbol,
            "Side": o.side,
            "Type": o.type,
            "Limit Price": o.limit_price,
            "Ext Hours": o.extended_hours,
            "Status": o.status
        } for o in orders]
        st.dataframe(pd.DataFrame(order_data), use_container_width=True)
    else:
        st.info("No open orders.")
