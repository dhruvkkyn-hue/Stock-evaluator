import pandas as pd
import numpy as np
import pandas_ta as ta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta

class GoatedEngine:
    def __init__(self, api_key, api_secret):
        self.client = StockHistoricalDataClient(api_key, api_secret)

    def get_data(self, symbols, timeframe_str, days_back, use_ext_hours):
        # Map timeframe
        tf_map = {"1Min": TimeFrame.Minute, "5Min": TimeFrame.Minute, "15Min": TimeFrame.Minute, "1Hour": TimeFrame.Hour, "1Day": TimeFrame.Day}
        tf = tf_map.get(timeframe_str, TimeFrame.Minute)
        
        start = datetime.now() - timedelta(days=days_back)
        
        # Extended hours handled via the request
        req = StockBarsRequest(
            symbol_or_symbols=symbols, 
            timeframe=tf, 
            start=start,
            feed='sip' # Use SIP for best institutional data
        )
        
        df = self.client.get_stock_bars(req).df
        df.index = df.index.get_level_values(1)
        
        # If not using extended hours, filter for 09:30 - 16:00 ET
        if not use_ext_hours:
            df = df.between_time('09:30', '16:00')
            
        return df

    @staticmethod
    def apply_strategy(df, params):
        df = df.copy()
        
        # 1. Institutional VWAP
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        df['vwap'] = df.groupby(df.index.date, group_keys=False).apply(
            lambda x: x['pv'].cumsum() / x['volume'].cumsum()
        )
        
        # 2. Indicators (EMA, ATR for Vol-Sizing, RSI for Exhaustion)
        df['ema_f'] = ta.ema(df['close'], length=params['ema_fast'])
        df['ema_s'] = ta.ema(df['close'], length=params['ema_slow'])
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # 3. GOATED Logic (Long and Short)
        # 1 = Long, -1 = Short, 0 = Flat
        df['signal'] = 0
        
        # Long: Trend is up, Price > VWAP, not overbought
        long_cond = (df['ema_f'] > df['ema_s']) & (df['close'] > df['vwap']) & (df['rsi'] < 70)
        # Short: Trend is down, Price < VWAP, not oversold
        short_cond = (df['ema_f'] < df['ema_s']) & (df['close'] < df['vwap']) & (df['rsi'] > 30)
        
        df.loc[long_cond, 'signal'] = 1
        df.loc[short_cond, 'signal'] = -1
        
        # Exit Logic: Trend flip
        df.loc[(df['signal'].shift(1) == 1) & (df['ema_f'] < df['ema_s']), 'signal'] = 0
        df.loc[(df['signal'].shift(1) == -1) & (df['ema_f'] > df['ema_s']), 'signal'] = 0
        
        return df.fillna(0)

    @staticmethod
    def run_backtest(df_map, config):
        all_ts = sorted(pd.concat([df.index.to_series() for df in df_map.values()]).unique())
        cash = config['initial_capital']
        positions = {s: 0 for s in df_map.keys()} # Shares held
        equity_curve = []
        
        for ts in all_ts:
            mtm_value = cash
            for symbol, df in df_map.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                
                # Update Mark-to-Market
                mtm_value += positions[symbol] * row['close']
                
                # Trade Execution (T+1 logic)
                idx = df.index.get_loc(ts)
                if idx == 0: continue
                
                prev_sig = df['signal'].iloc[idx-1]
                curr_sig = df['signal'].iloc[idx]
                
                # If signal changed
                if prev_sig != curr_sig:
                    # Liquidation of old position
                    cash += positions[symbol] * row['open']
                    positions[symbol] = 0
                    
                    # Entry into new position (Volatility Adjusted Sizing)
                    if curr_sig != 0:
                        # Risk 1% of equity per trade, size based on ATR
                        risk_amt = mtm_value * 0.01
                        atr = row['atr'] if row['atr'] > 0 else row['close'] * 0.01
                        shares = int(risk_amt / atr)
                        
                        # Go Long or Short
                        positions[symbol] = shares * curr_sig
                        cash -= positions[symbol] * row['open']
                        
                        # Apply slippage
                        cash -= abs(shares * (row['open'] * (config['slip_bps']/10000)))

            equity_curve.append(mtm_value)
            
        return pd.Series(equity_curve, index=all_ts)
