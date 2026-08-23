import pandas as pd
import numpy as np

class FeatureEngine:
    @staticmethod
    def apply_indicators(df):
        """Standardized indicator calculation."""
        # EMA
        df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # VWAP (Cumulative for the session)
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (df['tp'] * df['volume']).cumsum() / df['volume'].cumsum()
        
        # RVOL (Relative Volume)
        df['vol_sma'] = df['volume'].rolling(20).mean()
        df['rvol'] = df['volume'] / df['vol_sma']
        
        return df

    @staticmethod
    def get_signal(df):
        """Returns 1 (Long), -1 (Short), or 0 (Flat)"""
        if len(df) < 21: return 0
        
        last = df.iloc[-1]
        # Example Logic: Price above VWAP and EMA 9 > EMA 21
        if last['close'] > last['vwap'] and last['ema_9'] > last['ema_21']:
            return 1
        elif last['close'] < last['vwap'] and last['ema_9'] < last['ema_21']:
            return -1
        return 0
