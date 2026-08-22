import pandas as pd
import numpy as np
import pandas_ta as ta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta

class InstitutionalEngine:
    def __init__(self, api_key, api_secret):
        self.client = StockHistoricalDataClient(api_key, api_secret)

    def get_data(self, symbols, timeframe_str, days_back):
        tf = TimeFrame.Minute if "Min" in timeframe_str else TimeFrame.Day
        start = datetime.now() - timedelta(days=days_back)
        
        req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=tf, start=start)
        df = self.client.get_stock_bars(req).df
        df.index = df.index.get_level_values(1)
        return df

    @staticmethod
    def apply_strategy(df, params):
        df = df.copy()
        # 1. Institutional Session VWAP (Resets Daily)
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = df['tp'] * df['volume']
        df['vwap'] = df.groupby(df.index.date, group_keys=False).apply(
            lambda x: x['pv'].cumsum() / x['volume'].cumsum()
        )
        
        # 2. Refactored Indicators
        df['ema_f'] = ta.ema(df['close'], length=params['ema_fast'])
        df['ema_s'] = ta.ema(df['close'], length=params['ema_slow'])
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        # 3. Signal Generation (Signal at Close of Bar)
        df['signal'] = 0
        buy_cond = (df['ema_f'] > df['ema_s']) & (df['close'] > df['vwap'])
        df.loc[buy_cond, 'signal'] = 1
        return df

    @staticmethod
    def run_backtest(df_map, params, config):
        # Master timeline
        all_ts = sorted(pd.concat([df.index.to_series() for df in df_map.values()]).unique())
        
        cash = config['initial_capital']
        positions = {s: 0 for s in df_map.keys()}
        equity_curve = []
        
        for ts in all_ts:
            portfolio_value = cash
            for symbol, df in df_map.items():
                if ts not in df.index: continue
                
                row = df.loc[ts]
                # MTM Value
                portfolio_value += positions[symbol] * row['close']
                
                # EXECUTION LOGIC (Next-Bar Fill Fix)
                # We check the signal from the PREVIOUS bar to trade on CURRENT Open
                idx = df.index.get_loc(ts)
                if idx == 0: continue
                
                prev_signal = df['signal'].iloc[idx-1]
                current_open = row['open']
                
                # Apply Slippage
                slip = current_open * (config['slippage_bps'] / 10000)
                
                if prev_signal == 1 and positions[symbol] == 0:
                    # Buy
                    shares = (cash * 0.2) // (current_open + slip)
                    positions[symbol] = shares
                    cash -= shares * (current_open + slip)
                elif prev_signal == 0 and positions[symbol] > 0:
                    # Sell
                    cash += positions[symbol] * (current_open - slip)
                    positions[symbol] = 0
            
            equity_curve.append(portfolio_value)
            
        return pd.Series(equity_curve, index=all_ts)

    @staticmethod
    def monte_carlo(returns, simulations=100, days=252):
        results = []
        for _ in range(simulations):
            sim_rets = np.random.choice(returns, size=days, replace=True)
            results.append(np.cumprod(1 + sim_rets))
        return results
