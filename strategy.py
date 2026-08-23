import pandas as pd
import numpy as np

class FeatureEngine:
    @staticmethod
    def get_signals(df):
        if len(df) < 30: return "WARMING_UP", 0
        
        # 1. EMA Trend Ribbon
        df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # 2. Institutional VWAP
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (df['tp'] * df['volume']).cumsum() / df['volume'].cumsum()
        
        # 3. Volatility (ATR)
        high_low = df['high'] - df['low']
        df['atr'] = high_low.rolling(14).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 4. Slope Detection (Is the trend accelerating?)
        slope = last['ema_9'] - prev['ema_9']
        
        # --- THE SIGNAL ENGINE ---
        is_long = (last['close'] > last['vwap']) and (last['ema_9'] > last['ema_21']) and (slope > 0)
        is_short = (last['close'] < last['vwap']) and (last['ema_9'] < last['ema_21']) and (slope < 0)
        
        if is_long: return "BULL_TREND", 1
        if is_short: return "BEAR_TREND", -1
        return "NO_SIGNAL", 0
