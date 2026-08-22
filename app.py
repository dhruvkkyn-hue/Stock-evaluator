import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta

# --- 1. SETUP & SECRETS ---
st.set_page_config(page_title="Goated Algo Suite", layout="wide", page_icon="🚀")

try:
    # Key names must match exactly what you put in Streamlit Secrets
    API_KEY = st.secrets["ALPACA_KEY"]
    API_SECRET = st.secrets["ALPACA_SECRET"]
except Exception as e:
    st.error("⚠️ SECRETS ERROR: Ensure you added 'ALPACA_KEY' and 'ALPACA_SECRET' in the Streamlit Cloud Secrets sidebar.")
    st.stop()

# --- 2. THE ENGINE (Pure Pandas Math) ---
class InstitutionalEngine:
    @staticmethod
    def calculate_indicators(df, fast, slow):
        df = df.copy()
        # Session VWAP
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        df['vwap'] = df.groupby(df.index.date, group_keys=False).apply(
            lambda x: x['pv'].cumsum() / x['volume'].cumsum()
        )
        # EMAs
        df['ema_f'] = df['close'].ewm(span=fast, adjust=False).mean()
        df['ema_s'] = df['close'].ewm(span=slow, adjust=False).mean()
        # ATR
        tr = pd.concat([df['high'] - df['low'], 
                        np.abs(df['high'] - df['close'].shift()), 
                        np.abs(df['low'] - df['close'].shift())], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        
        # Signals: 1=Long, -1=Short
        df['signal'] = 0
        df.loc[(df['ema_f'] > df['ema_s']) & (df['close'] > df['vwap']), 'signal'] = 1
        df.loc[(df['ema_f'] < df['ema_s']) & (df['close'] < df['vwap']), 'signal'] = -1
        return df.fillna(0)

# --- 3. THE INTERFACE ---
st.title("🚀 Goated Institutional Truth Machine")
st.sidebar.header("Command Center")
symbols = st.sidebar.multiselect("Assets", ["AAPL", "TSLA", "NVDA", "AMD", "MSFT"], default=["NVDA", "TSLA"])
days = st.sidebar.slider("History (Days)", 1, 365, 30)

if st.button("🔥 RUN INSTITUTIONAL BACKTEST"):
    with st.spinner("Accessing SIP Data Feed..."):
        client = StockHistoricalDataClient(API_KEY, API_SECRET)
        start = datetime.now() - timedelta(days=days)
        
        # Fetch Data
        req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Minute, start=start)
        raw = client.get_stock_bars(req).df
        raw.index = raw.index.get_level_values(1)
        
        # Backtest Logic
        cash = 100000
        positions = {s: 0 for s in symbols}
        equity_curve = []
        
        # Process symbols
        processed_map = {s: InstitutionalEngine.calculate_indicators(raw[raw.index.get_level_values(0) == s], 12, 26) for s in symbols}
        timeline = sorted(pd.concat([df.index.to_series() for df in processed_map.values()]).unique())

        for ts in timeline:
            mtm = cash
            for s, df in processed_map.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                mtm += positions[s] * row['close']
                
                # Trade Execution (Signal at T, Execute at T+1)
                idx = df.index.get_loc(ts)
                if idx == 0: continue
                prev_sig = df['signal'].iloc[idx-1]
                
                if prev_sig != (1 if positions[s] > 0 else (-1 if positions[s] < 0 else 0)):
                    # Liquidation
                    cash += positions[s] * row['open']
                    positions[s] = 0
                    # New Entry (1% Risk)
                    if prev_sig != 0:
                        risk_amt = mtm * 0.01
                        shares = int(risk_amt / (row['atr'] if row['atr'] > 0 else row['close']*0.01))
                        positions[s] = shares * prev_sig
                        cash -= positions[s] * row['open']
            equity_curve.append(mtm)

        # Plotting
        equity_series = pd.Series(equity_curve, index=timeline)
        fig = go.Figure(go.Scatter(x=equity_series.index, y=equity_series.values, line=dict(color='#00ffcc')))
        fig.update_layout(template="plotly_dark", title="Mark-to-Market Equity")
        st.plotly_chart(fig, use_container_width=True)
        
        st.success(f"Final Return: {((equity_series.iloc[-1]/100000)-1):.2%}")
