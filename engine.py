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
        self.db = TradingDB()
        self.risk = RiskManager()
        self.trade_client = TradingClient(api_key, api_secret, paper=paper)
        self.data_client = StockHistoricalDataClient(api_key, api_secret)
        self.is_running = False

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._main_loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.is_running = False

    def _main_loop(self):
        while self.is_running:
            try:
                self.db.update_heartbeat(self.worker_id)
                self.process_markets()
                time.sleep(15) # Heartbeat
            except Exception as e:
                print(f"Engine Loop Error: {e}")
                time.sleep(10)

    def process_markets(self):
        account = self.trade_client.get_account()
        equity = float(account.equity)
        
        for symbol in self.symbols:
            # 1. Get Data
            start = datetime.now(timezone.utc) - timedelta(hours=6)
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start)
            bars = self.data_client.get_stock_bars(req).df
            if bars.empty: continue
            
            df = bars.xs(symbol)
            last_ts = df.index[-1]
            
            # 2. Check Bar Consistency
            if self.db.is_bar_processed(symbol, last_ts): continue

            # 3. Analyze Strategy
            signal_name, signal_val = FeatureEngine.get_signals(df)
            price = df.iloc[-1]['close']
            
            # 4. Check Risk and Execute
            if signal_val != 0:
                side = OrderSide.BUY if signal_val == 1 else OrderSide.SELL
                qty = self.risk.calculate_position_size(equity, price)
                
                # Check current positions to avoid spamming
                positions = self.trade_client.get_all_positions()
                can_trade, reason = self.risk.validate_execution(symbol, side, qty, positions)
                
                if can_trade:
                    # Deterministic Order ID (Idempotency)
                    order_id = f"apex_{symbol}_{int(last_ts.timestamp())}"
                    
                    self.trade_client.submit_order(MarketOrderRequest(
                        symbol=symbol, qty=qty, side=side, 
                        time_in_force=TimeInForce.GTC, client_order_id=order_id
                    ))
                    
                    self.db.log_trade(symbol, str(side), price, qty, signal_name, order_id)
                    self.db.mark_bar_processed(symbol, last_ts)
