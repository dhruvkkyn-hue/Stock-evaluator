import os
import time
from dataclasses import dataclass
from typing import List, Dict

@dataclass
class MarketTick:
    symbol: str
    timestamp: float
    last_price: float
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    volume: float

def load_watchlist(filepath: str = "watchlist.txt") -> List[str]:
    """Loads trading tickers dynamically from a .txt file."""
    if not os.path.exists(filepath):
        default_tickers = ["AAPL", "NVDA", "TSLA", "AMD"]
        with open(filepath, "w") as f:
            f.write("\n".join(default_tickers))
        return default_tickers

    with open(filepath, "r") as f:
        symbols = [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]
    return symbols

class InMemoryMarketState:
    """Stores incoming high-frequency market depth without database query delays."""
    def __init__(self, max_depth: int = 50):
        self.max_depth = max_depth
        self.state: Dict[str, List[MarketTick]] = {}

    def push_tick(self, tick: MarketTick):
        if tick.symbol not in self.state:
            self.state[tick.symbol] = []
        
        history = self.state[tick.symbol]
        history.append(tick)
        if len(history) > self.max_depth:
            history.pop(0)

    def get_history(self, symbol: str) -> List[MarketTick]:
        return self.state.get(symbol, [])
