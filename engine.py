import time
import uuid
import threading
from database import TradingDB
from strategy import FeatureEngine
from risk import RiskManager
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta, timezone

class TradingEngine:
    def __init__(self, api_key, api_secret, symbols, paper=True):
        self.worker_id = str(uuid.uuid4())
        self.db = TradingDB()
        self.risk = RiskManager()
        self.symbols = symbols
        self.trade_client = TradingClient(api_key, api_secret, paper=paper)
        self.data_client = StockHistoricalDataClient(api_key, api_secret)
        self.is_running = False

    def run_loop(self):
        self.is_running = True
        while self.is_running:
            self.db.update_heartbeat(self.worker_id)
            self.process_market()
            time.sleep(30) # Check every 30 seconds

    def process_market(self):
        for symbol in self.symbols:
            # 1. Fetch Data
            now = datetime.now(timezone.utc)
            start = now - timedelta(hours=5)
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start)
            df = self.data_client.get_stock_bars(req).df.xs(symbol)
            
            # 2. Only look at the last COMPLETED bar
            last_bar_ts = df.index[-1]
            if self.db.is_bar_processed(symbol, last_bar_ts):
                continue
            
            # 3. Get Signal
            df = FeatureEngine.apply_indicators(df)
            signal = FeatureEngine.get_signal(df)
            
            # 4. Execute with Idempotency
            if signal != 0:
                # Execution logic using RiskManager and client_order_id
                # self.trade_client.submit_order(...)
                self.db.mark_bar_processed(symbol, last_bar_ts)
