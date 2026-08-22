import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# Alpaca SDK
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

# --- 1. SYSTEM INITIALIZATION ---
st.set_page_config(page_title="Apex Predator Intraday", layout="wide", page_icon="🦈")
st_autorefresh(interval=15000, key="bot_heartbeat") 

try:
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
    IS_PAPER = st.secrets.get("IS_PAPER", True)
    
    trading_client = TradingClient(API_KEY, API_SECRET, paper=IS_PAPER)
    data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
except Exception:
    st.error("⚠️ SECRETS ERROR: Add ALPACA_KEY and ALPACA_SECRET to Streamlit Secrets.")
    st.stop()

# --- 2. ALPHA ENGINE: INTRADAY JUICE ---
class AlphaEngine:
    @staticmethod
    def analyze(df):
        if df is None or df.empty: return None
        df = df.copy()
        
        # A. TREND HIERARCHY (Institutional Confluence)
        # Fast EMA (9), Medium EMA (21), Slow EMA (50)
        df['ema_9'] = df.groupby(level=0)['close'].transform(lambda x: x.ewm(span=9).mean())
        df['ema_21'] = df.groupby(level=0)['close'].transform(lambda x: x.ewm(span=21).mean())
        df['ema_50'] = df.groupby(level=0)['close'].transform(lambda x: x.ewm(span=50).mean())
        
        # B. INSTITUTIONAL VALUE (Anchored VWAP)
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        df['date'] = df.index.get_level_values(1).date
        gb = df.groupby([df.index.get_level_values(0), 'date'])
        df['vwap'] = gb['pv'].cumsum() / gb['volume'].cumsum()
        
        # C. RELATIVE VOLUME (RVOL) - Institutional Buying Footprint
        # Is volume 2x higher than the last 20 bars?
        df['vol_ma'] = df.groupby(level=0)['volume'].transform(lambda x: x.rolling(20).mean())
        df['rvol'] = df['volume'] / df['vol_ma']
        
        # D. VOLATILITY (ATR)
        def get_atr(g):
            tr = pd.concat([g['high']-g['low'], abs(g['high']-g['close'].shift()), abs(g['low']-g['close'].shift())], axis=1).max(axis=1)
            return tr.rolling(14).mean()
        df['atr'] = df.groupby(level=0, group_keys=False).apply(get_atr)

        # --- THE GOATED SIGNAL FRAMEWORK ---
        df['signal'] = 0
        # LONG: Price > VWAP AND 9 > 21 > 50 AND high RVOL
        long_cond = (df['close'] > df['vwap']) & (df['ema_9'] > df['ema_21']) & (df['ema_21'] > df['ema_50']) & (df['rvol'] > 1.2)
        # SHORT: Price < VWAP AND 9 < 21 < 50 AND high RVOL
        short_cond = (df['close'] < df['vwap']) & (df['ema_9'] < df['ema_21']) & (df['ema_21'] < df['ema_50']) & (df['rvol'] > 1.2)
        
        df.loc[long_cond, 'signal'] = 1
        df.loc[short_cond, 'signal'] = -1
        
        return df

# --- 3. UI & ACCOUNT ---
acc = trading_client.get_account()
st.title("🦈 APEX PREDATOR: Institutional Intraday")

h1, h2, h3, h4 = st.columns(4)
h1.metric("Equity", f"${float(acc.equity):,.2f}")
h2.metric("Buying Power", f"${float(acc.buying_power):,.2f}")
h3.metric("Daily P/L", f"${float(acc.equity) - float(acc.last_equity):,.2f}")

with h4:
    if st.button("🚨 PANIC: LIQUIDATE EVERYTHING", type="primary", use_container_width=True):
        trading_client.close_all_positions(cancel_orders=True)
        st.toast("TERMINATING ALL EXPOSURE...")

# --- 4. BOT CONFIG ---
st.sidebar.header("🤖 Bot Settings")
bot_active = st.sidebar.toggle("RUN AUTONOMOUS ENGINE", value=False)
risk_per_trade = st.sidebar.slider("Risk Per Trade (%)", 0.1, 5.0, 1.0)
watchlist = st.sidebar.multiselect("Watchlist", ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "META", "QQQ", "SPY", "COIN", "PLTR"], default=["NVDA", "TSLA", "AMD", "AAPL"])

# --- 5. EXECUTION ENGINE (The fix for your 403 error) ---
if watchlist:
    try:
        # Fetch Data
        start_dt = datetime.now() - timedelta(hours=24)
        raw_df = data_client.get_stock_bars(StockBarsRequest(symbol_or_symbols=watchlist, timeframe=TimeFrame.Minute, start=start_dt)).df
        
        # Analyze
        processed = AlphaEngine.analyze(raw_df)
        latest = processed.groupby(level=0).tail(1).reset_index()
        
        st.subheader("Market Intelligence")
        st.dataframe(latest[['symbol', 'close', 'vwap', 'rvol', 'signal']].style.background_gradient(subset=['signal'], cmap='RdYlGn'), use_container_width=True)

        if bot_active:
            # 1. Get ALL open orders to prevent "insufficient qty" (Conflict Resolution)
            open_orders = trading_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
            pending_symbols = [o.symbol for o in open_orders]

            for _, row in latest.iterrows():
                sym, sig, price, atr = row['symbol'], row['signal'], row['close'], row['atr']
                
                # SKIP if there's already a pending order for this stock
                if sym in pending_symbols:
                    continue 

                try:
                    pos = trading_client.get_open_position(sym)
                    current_side = 1 if int(pos.qty) > 0 else -1
                except:
                    current_side = 0

                if sig != current_side:
                    # CLOSE existing
                    if current_side != 0:
                        trading_client.close_position(sym)
                        st.toast(f"Closing {sym}")
                    
                    # OPEN new if signal is strong
                    if sig != 0:
                        risk_usd = float(acc.equity) * (risk_per_trade / 100)
                        # Sizing: Risk Amount / ATR Stop distance
                        qty = int(risk_usd / max(atr, price * 0.01))
                        
                        if qty > 0:
                            trading_client.submit_order(MarketOrderRequest(
                                symbol=sym, qty=qty, 
                                side=OrderSide.BUY if sig == 1 else OrderSide.SELL,
                                time_in_force=TimeInForce.GTC, extended_hours=True
                            ))
                            st.toast(f"OPENING {sym} {'LONG' if sig==1 else 'SHORT'}")
    except Exception as e:
        st.error(f"Engine Sync Error: {e}")

st.divider()
st.subheader("Current Positions")
try:
    positions = trading_client.get_all_positions()
    if positions:
        st.dataframe(pd.DataFrame([{
            'Symbol': p.symbol, 'Side': p.side, 'Qty': p.qty, 'P/L %': f"{(float(p.unrealized_plpc)*100):.2f}%"
        } for p in positions]), use_container_width=True)
    else:
        st.info("No active trades.")
except:
    pass
