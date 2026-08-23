import time
import uuid
from datetime import datetime, timezone
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from database import TradingDB

class TradingEngine:
    def __init__(self, api_key, api_secret, symbols, paper=True):
        self.worker_id = str(uuid.uuid4())
        self.db = TradingDB()
        self.symbols = symbols
        self.is_running = False  # <--- THIS MUST BE HERE
        
        # Initialize Clients
        self.trade_client = TradingClient(api_key, api_secret, paper=paper)
        self.data_client = StockHistoricalDataClient(api_key, api_secret)

    def run_loop(self):
        self.is_running = True
        while self.is_running:
            try:
                self.db.update_heartbeat(self.worker_id)
                # Market logic goes here
                time.sleep(10) 
            except Exception as e:
                print(f"Error in loop: {e}")
                time.sleep(10)
