import time
import uuid
import threading
from database import TradingDB
from strategy import FeatureEngine
from risk import RiskManager
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta, timezone

class TradingEngine:
    def __init__(self, api_key, api_secret, symbols, paper=True):
        self.worker_id = str(uuid.uuid4())
        self.symbols = symbols
        self.paper = paper # Fixed the AttributeError source
        self.db = TradingDB()
        self.risk = RiskManager()
        self.trade_client = TradingClient(api_key, api_secret, paper=paper)
        self.data_client = StockHistoricalDataClient(api_key, api_secret)
        self.is_running = False

    def start(self):
        if not self.is_running:
            self.is_running = True
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.is_running:
            try:
                self.db.update_heartbeat(self.worker_id)
                self._scan()
                time.sleep(20) 
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(10)

    def _scan(self):
        acc = self.trade_client.get_account()
        equity = float(acc.equity)
        
        for symbol in self.symbols:
            start = datetime.now(timezone.utc) - timedelta(hours=4)
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start)
            bars = self.data_client.get_stock_bars(req).df
            if bars.empty: continue
            
            df = bars.xs(symbol)
            last_ts = df.index[-1]
            
            if self.db.is_bar_processed(symbol, last_ts): continue

            signal_name, val = FeatureEngine.get_signals(df)
            if val != 0:
                pos = self.trade_client.get_all_positions()
                if self.risk.is_safe_to_trade(symbol, pos):
                    price = df.iloc[-1]['close']
                    qty = self.risk.calculate_qty(equity, price)
                    order_id = f"v5_{symbol}_{int(last_ts.timestamp())}"
                    
                    self.trade_client.submit_order(MarketOrderRequest(
                        symbol=symbol, qty=qty, 
                        side=OrderSide.BUY if val == 1 else OrderSide.SELL,
                        time_in_force=TimeInForce.GTC, client_order_id=order_id
                    ))
                    self.db.log_trade(symbol, "BUY" if val==1 else "SELL", price, qty, signal_name, order_id)
                    self.db.mark_bar_processed(symbol, last_ts)
