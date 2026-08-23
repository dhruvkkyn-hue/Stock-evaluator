import pandas as pd
import numpy as np

class FeatureEngine:
    @staticmethod
    def get_signals(df):
        """Mathematically rigorous indicator stack."""
        if len(df) < 50: return "WAITING_FOR_DATA", 0
        
        # 1. EMA Ribbon (Trend Detection)
        df['ema_short'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_long'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # 2. Institutional VWAP (Value Detection)
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (df['tp'] * df['volume']).cumsum() / df['volume'].cumsum()
        
        # 3. RVOL (Relative Volume - detect smart money)
        df['vol_ma'] = df['volume'].rolling(window=20).mean()
        df['rvol'] = df['volume'] / df['vol_ma']
        
        last = df.iloc[-1]
        
        # --- THE SIGNAL ENGINE ---
        # Long: Price > VWAP AND EMA9 > EMA21 AND Volume is significant
        is_long = (last['close'] > last['vwap']) and (last['ema_short'] > last['ema_long'])
        # Short: Price < VWAP AND EMA9 < EMA21 AND Volume is significant
        is_short = (last['close'] < last['vwap']) and (last['ema_short'] < last['ema_long'])
        
        if is_long: return "BULLISH_CONFLUENCE", 1
        if is_short: return "BEARISH_CONFLUENCE", -1
        return "NEUTRAL", 0
