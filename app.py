import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta

class GoatedEngine:
    def __init__(self, api_key, api_secret):
        self.client = StockHistoricalDataClient(api_key, api_secret)

    def get_data(self, symbols, timeframe_str, days_back, use_ext_hours):
        tf_map = {"1Min": TimeFrame.Minute, "5Min": TimeFrame.Minute, "15Min": TimeFrame.Minute, "1Hour": TimeFrame.Hour, "1Day": TimeFrame.Day}
        tf = tf_map.get(timeframe_str, TimeFrame.Minute)
        start = datetime.now() - timedelta(days=days_back)
        
        req = StockBarsRequest(
            symbol_or_symbols=symbols, 
            timeframe=tf, 
            start=start,
            feed='sip'
        )
        
        df = self.client.get_stock_bars(req).df
        df.index = df.index.get_level_values(1)
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
        
        # 2. Pure Pandas EMA (No pandas-ta needed)
        df['ema_f'] = df['close'].ewm(span=params['ema_fast'], adjust=False).mean()
        df['ema_s'] = df['close'].ewm(span=params['ema_slow'], adjust=False).mean()
        
        # 3. Pure Pandas ATR
        high_low = df['high'] - df['low']
        high_cp = np.abs(df['high'] - df['close'].shift())
        low_cp = np.abs(df['low'] - df['close'].shift())
        df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()
        
        # 4. Pure Pandas RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # 5. Signal Logic
        df['signal'] = 0
        long_cond = (df['ema_f'] > df['ema_s']) & (df['close'] > df['vwap']) & (df['rsi'] < 70)
        short_cond = (df['ema_f'] < df['ema_s']) & (df['close'] < df['vwap']) & (df['rsi'] > 30)
        
        df.loc[long_cond, 'signal'] = 1
        df.loc[short_cond, 'signal'] = -1
        return df.fillna(0)

    @staticmethod
    def run_backtest(df_map, config):
        # Flatten all timestamps from all symbols
        all_ts = sorted(pd.concat([df.index.to_series() for df in df_map.values()]).unique())
        cash = config['initial_capital']
        positions = {s: 0 for s in df_map.keys()}
        equity_curve = []
        
        for ts in all_ts:
            mtm_value = cash
            for symbol, df in df_map.items():
                if ts not in df.index: continue
                row = df.loc[ts]
                
                # Portfolio MTM
                mtm_value += positions[symbol] * row['close']
                
                # T+1 Logic: Look at signal from PREVIOUS bar to trade at CURRENT bar open
                idx = df.index.get_loc(ts)
                if idx == 0: continue
                
                prev_sig = df['signal'].iloc[idx-1]
                curr_sig = df['signal'].iloc[idx]
                
                if prev_sig != curr_sig:
                    # Liquidation
                    cash += positions[symbol] * row['open']
                    positions[symbol] = 0
                    
                    # New Entry
                    if curr_sig != 0:
                        risk_amt = mtm_value * 0.01
                        atr = row['atr'] if row['atr'] > 0 else row['close'] * 0.01
                        shares = int(risk_amt / atr)
                        
                        positions[symbol] = shares * curr_sig
                        cash -= positions[symbol] * row['open']
                        # Slippage
                        cash -= abs(shares * (row['open'] * (config['slip_bps']/10000)))

            equity_curve.append(mtm_value)
            
        return pd.Series(equity_curve, index=all_ts)
