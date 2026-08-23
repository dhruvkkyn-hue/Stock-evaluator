import sqlite3
import pandas as pd
from datetime import datetime, timezone

class TradingDB:
    def __init__(self, db_path="trading_platform.db"):
        self.db_path = db_path
        self._create_tables()

    def _create_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            # Worker Lease: Prevents multiple bots from running
            conn.execute("""CREATE TABLE IF NOT EXISTS worker_lease 
                         (id INTEGER PRIMARY KEY, worker_id TEXT, heartbeat TIMESTAMP)""")
            # Trade Journal: Audit trail
            conn.execute("""CREATE TABLE IF NOT EXISTS trade_journal 
                         (id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT, side TEXT, 
                          price REAL, qty REAL, client_order_id TEXT UNIQUE)""")
            # Processed Bars: Prevents double-trading same minute
            conn.execute("""CREATE TABLE IF NOT EXISTS processed_bars 
                         (symbol TEXT, timestamp TEXT, PRIMARY KEY(symbol, timestamp))""")

    def update_heartbeat(self, worker_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("REPLACE INTO worker_lease (id, worker_id, heartbeat) VALUES (1, ?, ?)",
                         (worker_id, datetime.now(timezone.utc).isoformat()))

    def is_bar_processed(self, symbol, timestamp):
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute("SELECT 1 FROM processed_bars WHERE symbol=? AND timestamp=?", 
                               (symbol, str(timestamp))).fetchone()
            return res is not None

    def mark_bar_processed(self, symbol, timestamp):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO processed_bars (symbol, timestamp) VALUES (?, ?)",
                         (symbol, str(timestamp)))
