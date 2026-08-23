import sqlite3
import pandas as pd
from datetime import datetime, timezone

class TradingDB:
    def __init__(self, db_path="trading_data.db"):
        self.db_path = db_path
        self._create_tables()

    def _create_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            # Persistent state for the worker
            conn.execute("""CREATE TABLE IF NOT EXISTS system_state 
                         (key TEXT PRIMARY KEY, value TEXT)""")
            # Lease to prevent duplicate workers
            conn.execute("""CREATE TABLE IF NOT EXISTS worker_lease 
                         (id INTEGER PRIMARY KEY, worker_id TEXT, heartbeat TIMESTAMP)""")
            # Audit trail for every single trade
            conn.execute("""CREATE TABLE IF NOT EXISTS trade_journal 
                         (id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT, side TEXT, 
                          price REAL, qty REAL, signal_type TEXT, client_order_id TEXT UNIQUE)""")
            # Bar tracking to prevent double-processing
            conn.execute("""CREATE TABLE IF NOT EXISTS processed_bars 
                         (symbol TEXT, timestamp TEXT, PRIMARY KEY(symbol, timestamp))""")
            
    def log_trade(self, symbol, side, price, qty, signal_type, order_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""INSERT INTO trade_journal (timestamp, symbol, side, price, qty, signal_type, client_order_id)
                         VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (datetime.now(timezone.utc).isoformat(), symbol, side, price, qty, signal_type, order_id))

    def mark_bar_processed(self, symbol, timestamp):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO processed_bars (symbol, timestamp) VALUES (?, ?)",
                         (symbol, str(timestamp)))

    def is_bar_processed(self, symbol, timestamp):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT 1 FROM processed_bars WHERE symbol=? AND timestamp=?", 
                               (symbol, str(timestamp))).fetchone() is not None

    def get_logs(self, limit=20):
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql(f"SELECT * FROM trade_journal ORDER BY id DESC LIMIT {limit}", conn)

    def update_heartbeat(self, worker_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("REPLACE INTO worker_lease (id, worker_id, heartbeat) VALUES (1, ?, ?)",
                         (worker_id, datetime.now(timezone.utc).isoformat()))
