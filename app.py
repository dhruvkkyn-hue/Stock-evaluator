import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# -------------------------------------------------------------------
# 1. LOGGING & AUDIT SETUP
# -------------------------------------------------------------------
def setup_logging():
    logger = logging.getLogger("QUANT_CORE")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    file_handler = logging.FileHandler("audit_log.txt", mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

logger = setup_logging()

# -------------------------------------------------------------------
# 2. DATA MODELS & ENUMS
# -------------------------------------------------------------------
class MarketRegime(Enum):
    HIGH_CONVICTION_BULL = "BULL_TREND"
    HIGH_CONVICTION_BEAR = "BEAR_TREND"
    CHOPPY_RANGE = "RANGEBOUND"
    UNSAFE_VOLATILITY = "UNSAFE_VOLATILITY"

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

# -------------------------------------------------------------------
# 3. HIGH-CONVICTION FRAMEWORK ENGINES
# -------------------------------------------------------------------
class RegimeDetector:
    """Filters out choppy markets. Trading is allowed ONLY in prime regimes."""
    @staticmethod
    def classify(ticks: List[MarketTick]) -> MarketRegime:
        if len(ticks) < 15:
            return MarketRegime.CHOPPY_RANGE

        prices = np.array([t.last_price for t in ticks])
        returns = np.diff(prices) / prices[:-1]
        volatility = np.std(returns)

        # Unsafe market conditions filter
        if volatility > 0.025:
            return MarketRegime.UNSAFE_VOLATILITY

        ema_fast = pd.Series(prices).ewm(span=3).mean().iloc[-1]
        ema_slow = pd.Series(prices).ewm(span=10).mean().iloc[-1]
        trend_strength = (ema_fast - ema_slow) / ema_slow

        if trend_strength > 0.0015:
            return MarketRegime.HIGH_CONVICTION_BULL
        elif trend_strength < -0.0015:
            return MarketRegime.HIGH_CONVICTION_BEAR
        else:
            return MarketRegime.CHOPPY_RANGE

class AlphaSignalEngine:
    """Calculates triple-confirmed setup signals with cost-adjusted edge."""
    @staticmethod
    def evaluate(ticks: List[MarketTick], regime: MarketRegime) -> Tuple[str, float, float]:
        """Returns: (Action: BUY/SELL/HOLD, Confidence/ProbWin, Calculated EV)"""
        if regime in [MarketRegime.CHOPPY_RANGE, MarketRegime.UNSAFE_VOLATILITY]:
            return "HOLD", 0.0, 0.0

        latest = ticks[-1]
        prices = np.array([t.last_price for t in ticks])
        volumes = np.array([t.volume for t in ticks])

        # Microstructure: Order Book Imbalance (OBI)
        depth_denom = (latest.bid_size + latest.ask_size)
        obi = (latest.bid_size - latest.ask_size) / depth_denom if depth_denom > 0 else 0.0

        # VWAP Deviation
        pv = prices * volumes
        cum_vol = np.sum(volumes)
        vwap = np.sum(pv) / cum_vol if cum_vol > 0 else latest.last_price
        vwap_dev = (latest.last_price - vwap) / vwap

        # Volume Surge Ratio
        avg_vol = np.mean(volumes)
        vol_surge = latest.volume / avg_vol if avg_vol > 0 else 1.0

        # Triple Confirmation Logic
        spread = latest.ask - latest.bid
        cost_barrier = (spread / latest.last_price) + 0.0005  # Includes slippage buffer

        if regime == MarketRegime.HIGH_CONVICTION_BULL and obi > 0.25 and vwap_dev < 0.001 and vol_surge > 1.3:
            prob_win = 0.62
            expected_gain = 0.004  # 40 bps
            expected_loss = 0.002  # 20 bps
            ev = (prob_win * expected_gain) - ((1 - prob_win) * expected_loss) - cost_barrier
            
            if ev > 0.0008:  # Minimum edge threshold
                return "BUY", prob_win, ev

        elif regime == MarketRegime.HIGH_CONVICTION_BEAR and obi < -0.25 and vwap_dev > -0.001 and vol_surge > 1.3:
            prob_win = 0.60
            expected_gain = 0.004
            expected_loss = 0.002
            ev = (prob_win * expected_gain) - ((1 - prob_win) * expected_loss) - cost_barrier
            
            if ev > 0.0008:
                return "SELL", prob_win, ev

        return "HOLD", 0.0, 0.0

# -------------------------------------------------------------------
# 4. SYSTEM COORDINATOR & MANUAL OVERRIDE TERMINAL
# -------------------------------------------------------------------
class ExecutionSystem:
    def __init__(self, capital: float = 100000.0):
        self.capital = capital
        self.market_cache: Dict[str, List[MarketTick]] = {}
        self.positions: Dict[str, int] = {}
        self.autotrade_enabled = True

    async def process_tick(self, tick: MarketTick):
        if tick.symbol not in self.market_cache:
            self.market_cache[tick.symbol] = []
            
        cache = self.market_cache[tick.symbol]
        cache.append(tick)
        if len(cache) > 40:
            cache.pop(0)

        if not self.autotrade_enabled:
            return

        regime = RegimeDetector.classify(cache)
        action, prob_win, ev = AlphaSignalEngine.evaluate(cache, regime)

        if action != "HOLD":
            current_pos = self.positions.get(tick.symbol, 0)
            if action == "BUY" and current_pos == 0:
                # Fractional Kelly Sizing
                qty = max(1, int((self.capital * 0.05) // tick.last_price))
                self.positions[tick.symbol] = qty
                logger.info(
                    f"⚡ [AUTO-BUY EXECUTED] {qty} shares of {tick.symbol} @ ${tick.last_price:.2f} | "
                    f"Regime: {regime.value} | Win Prob: {prob_win:.0%} | EV: +{ev*10000:.1f} bps"
                )
            elif action == "SELL" and current_pos > 0:
                logger.info(f"⚡ [AUTO-SELL EXECUTED] Liquidated {current_pos} shares of {tick.symbol} @ ${tick.last_price:.2f}")
                self.positions[tick.symbol] = 0

    async def manual_cli_listener(self):
        """Non-blocking input listener for real-time manual trading overrides."""
        loop = asyncio.get_event_loop()
        print("\n" + "="*60)
        print("🕹️  MANUAL CONTROL OVERRIDE TERMINAL ACTIVE")
        print("Commands:")
        print("  b <symbol> <qty>  -> Manual Market Buy")
        print("  s <symbol> <qty>  -> Manual Market Sell")
        print("  toggle            -> Enable / Disable Autonomous Bot")
        print("  status            -> Show Portfolio Positions & System State")
        print("  panic             -> Flush / Liquidate All Positions Instantly")
        print("="*60 + "\n")

        while True:
            user_input = await loop.run_in_executor(None, input, "COMMAND > ")
            parts = user_input.strip().split()
            if not parts:
                continue

            cmd = parts[0].lower()
            if cmd == "toggle":
                self.autotrade_enabled = not self.autotrade_enabled
                state = "ACTIVE 🟢" if self.autotrade_enabled else "PAUSED 🔴"
                logger.info(f"--> Autonomous Trading State Changed: {state}")

            elif cmd == "status":
                logger.info(f"Portfolio Capital: ${self.capital:,.2f} | Open Positions: {self.positions}")

            elif cmd == "panic":
                logger.warning("🚨 EMERGENCY PANIC FLUSH INITIATED! Liquidating all holdings...")
                for sym, qty in list(self.positions.items()):
                    if qty > 0:
                        logger.info(f"🔥 FLUSHED {qty} shares of {sym}")
                        self.positions[sym] = 0

            elif cmd in ["b", "s"] and len(parts) == 3:
                sym = parts[1].upper()
                qty = int(parts[2])
                if cmd == "b":
                    self.positions[sym] = self.positions.get(sym, 0) + qty
                    logger.info(f"📥 [MANUAL BUY OVERRIDE] Bought {qty} shares of {sym}")
                else:
                    curr = self.positions.get(sym, 0)
                    sell_qty = min(curr, qty) if curr > 0 else qty
                    self.positions[sym] = max(0, curr - sell_qty)
                    logger.info(f"📤 [MANUAL SELL OVERRIDE] Sold {sell_qty} shares of {sym}")

# -------------------------------------------------------------------
# 5. ASYNCHRONOUS EVENT LOOP SIMULATION
# -------------------------------------------------------------------
async def mock_market_stream(system: ExecutionSystem):
    symbols = ["AAPL", "NVDA", "TSLA"]
    prices = {"AAPL": 180.0, "NVDA": 120.0, "TSLA": 220.0}

    while True:
        await asyncio.sleep(0.05)  # 50ms tick feed rate
        sym = np.random.choice(symbols)
        prices[sym] += np.random.normal(0.02, 0.15)
        
        tick = MarketTick(
            symbol=sym,
            timestamp=time.time(),
            last_price=round(prices[sym], 2),
            bid=round(prices[sym] - 0.02, 2),
            ask=round(prices[sym] + 0.02, 2),
            bid_size=float(np.random.randint(100, 1000)),
            ask_size=float(np.random.randint(100, 500)),
            volume=float(np.random.randint(50, 500))
        )
        await system.process_tick(tick)

async def main():
    system = ExecutionSystem()
    logger.info("Initializing Asynchronous High-Conviction Engine...")

    await asyncio.gather(
        mock_market_stream(system),
        system.manual_cli_listener()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSystem shut down successfully.")
