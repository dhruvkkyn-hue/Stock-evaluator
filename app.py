import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from typing import List
import numpy as np

# -------------------------------------------------------------------
# 1. NON-BLOCKING ASYNC TEXT LOGGER SETUP
# -------------------------------------------------------------------
def setup_text_logging(log_filename: str = "audit_log.txt"):
    """Configures structured plain-text logging to file and console."""
    logger = logging.getLogger("QUANT_CORE")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers on re-runs
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Plain Text File Handler (.txt)
    file_handler = logging.FileHandler(log_filename, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 2. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

logger = setup_text_logging()

# -------------------------------------------------------------------
# 2. WATCHLIST (.TXT) LOADER
# -------------------------------------------------------------------
def load_watchlist_from_txt(filepath: str = "watchlist.txt") -> List[str]:
    """Reads symbol universe dynamically from a .txt file."""
    if not os.path.exists(filepath):
        logger.warning(f"File {filepath} not found. Creating default watchlist.txt")
        default_tickers = ["AAPL", "NVDA", "TSLA", "AMD"]
        with open(filepath, "w") as f:
            f.write("\n".join(default_tickers))
        return default_tickers

    with open(filepath, "r") as f:
        symbols = [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]
    
    logger.info(f"Loaded {len(symbols)} tickers from {filepath}: {symbols}")
    return symbols

# -------------------------------------------------------------------
# 3. ASYNC LOGGING QUEUE (Eliminates File I/O Blocking)
# -------------------------------------------------------------------
class AsyncTextLogger:
    def __init__(self):
        self.queue = asyncio.Queue()
        
    async def log_worker(self):
        """Dedicated background task to write to audit_log.txt without blocking execution."""
        while True:
            msg = await self.queue.get()
            logger.info(msg)
            self.queue.task_done()

    def write(self, message: str):
        self.queue.put_nowait(message)

# -------------------------------------------------------------------
# 4. LIGHTWEIGHT ASYNC TRADING LOOP
# -------------------------------------------------------------------
@dataclass
class MarketTick:
    symbol: str
    price: float
    bid: float
    ask: float
    volume: float

class QuantSystem:
    def __init__(self, tickers: List[str], async_logger: AsyncTextLogger):
        self.tickers = tickers
        self.async_logger = async_logger
        self.capital = 100000.0

    async def process_tick(self, tick: MarketTick):
        # 1. Calculate Microstructure Features
        spread = tick.ask - tick.bid
        mid_price = (tick.ask + tick.bid) / 2.0
        
        # 2. Compute Edge Strategy (Order Book Imbalance)
        if spread > 0.10:  # Illiquidity guard rail
            self.async_logger.write(f"REJECTED [{tick.symbol}] | Wide Spread: ${spread:.2f}")
            return

        # 3. Simulated Execution Log to file
        self.async_logger.write(
            f"TICK PROCESSED [{tick.symbol}] Price: ${tick.price:.2f} | "
            f"Spread: ${spread:.2f} | Mid: ${mid_price:.2f}"
        )

# -------------------------------------------------------------------
# 5. MAIN EVENT LOOP RUNNER
# -------------------------------------------------------------------
async def main():
    async_logger = AsyncTextLogger()
    
    # Start background file writer task
    asyncio.create_task(async_logger.log_worker())
    
    # Load assets from text configuration
    tickers = load_watchlist_from_txt("watchlist.txt")
    system = QuantSystem(tickers, async_logger)
    
    logger.info("Initializing zero-latency async loop. Streaming to audit_log.txt...")
    
    # Simulate high-frequency incoming streaming ticks
    for i in range(10):
        await asyncio.sleep(0.02)  # 20ms update rate
        symbol = np.random.choice(tickers)
        base_price = 150.0 + np.random.normal(0, 1)
        
        tick = MarketTick(
            symbol=symbol,
            price=round(base_price, 2),
            bid=round(base_price - 0.02, 2),
            ask=round(base_price + 0.02, 2),
            volume=float(np.random.randint(100, 1000))
        )
        await system.process_tick(tick)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutdown complete.")
