import asyncio
import logging
import sys
import time
from enum import Enum
from typing import Tuple, Dict, List, Optional

import numpy as np
import pandas as pd

from config import (
    INITIAL_CAPITAL, MAX_DRAWDOWN_PCT, MAX_POSITION_PCT,
    MIN_EXPECTED_EDGE_BPS, COMMISSION_PER_SHARE,
    WATCHLIST_FILE, AUDIT_LOG_FILE
)
from data_layer import MarketTick, InMemoryMarketState, load_watchlist

# -------------------------------------------------------------------
# 1. NON-BLOCKING AUDIT LOGGING
# -------------------------------------------------------------------
def setup_audit_logging():
    logger = logging.getLogger("QUANT_SYSTEM")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler(AUDIT_LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

logger = setup_audit_logging()

# -------------------------------------------------------------------
# 2. MARKET REGIME CLASSIFIER
# -------------------------------------------------------------------
class MarketRegime(Enum):
    BULL_TREND = "HIGH_CONVICTION_BULL"
    BEAR_TREND = "HIGH_CONVICTION_BEAR"
    RANGEBOUND = "RANGEBOUND_CHOP"
    HIGH_VOLATILITY = "UNSAFE_HIGH_VOLATILITY"

class RegimeEngine:
    @staticmethod
    def detect(ticks: List[MarketTick]) -> MarketRegime:
        if len(ticks) < 20:
            return MarketRegime.RANGEBOUND

        prices = np.array([t.last_price for t in ticks])
        returns = np.diff(prices) / prices[:-1]
        realized_vol = np.std(returns)

        # Unsafe Volatility Filter (Do not trade if chop/vol is extreme)
        if realized_vol > 0.02:
            return MarketRegime.HIGH_VOLATILITY

        ema_fast = pd.Series(prices).ewm(span=3).mean().iloc[-1]
        ema_slow = pd.Series(prices).ewm(span=12).mean().iloc[-1]
        trend_slope = (ema_fast - ema_slow) / ema_slow

        if trend_slope > 0.0012:
            return MarketRegime.BULL_TREND
        elif trend_slope < -0.0012:
            return MarketRegime.BEAR_TREND
        else:
            return MarketRegime.RANGEBOUND

# -------------------------------------------------------------------
# 3. EXPECTED EDGE & ALPHA SIGNAL CALCULATOR
# -------------------------------------------------------------------
class AlphaEngine:
    @staticmethod
    def evaluate_opportunity(
        ticks: List[MarketTick], 
        regime: MarketRegime
    ) -> Tuple[str, float, float, Optional[str]]:
        """
        Returns: 
        (Action: BUY/SELL/HOLD, Win Prob, EV Net Costs, Option Advice)
        """
        # Patient Waiting: Reject trades in chop or extreme vol
        if regime in [MarketRegime.RANGEBOUND, MarketRegime.HIGH_VOLATILITY]:
            return "HOLD", 0.0, 0.0, None

        latest = ticks[-1]
        prices = np.array([t.last_price for t in ticks])
        volumes = np.array([t.volume for t in ticks])

        # Microstructure 1: Order Book Imbalance (OBI)
        depth_denom = (latest.bid_size + latest.ask_size)
        obi = (latest.bid_size - latest.ask_size) / depth_denom if depth_denom > 0 else 0.0

        # Microstructure 2: VWAP Deviation
        pv = prices * volumes
        cum_vol = np.sum(volumes)
        vwap = np.sum(pv) / cum_vol if cum_vol > 0 else latest.last_price
        vwap_dev = (latest.last_price - vwap) / vwap

        # Microstructure 3: Volume Acceleration
        avg_vol = np.mean(volumes)
        vol_surge = latest.volume / avg_vol if avg_vol > 0 else 1.0

        # Cost Drag Calculation
        spread = latest.ask - latest.bid
        roundtrip_cost = (spread / latest.last_price) + ((COMMISSION_PER_SHARE * 2) / latest.last_price)

        # Triple Confirmation Entry Logic
        if regime == MarketRegime.BULL_TREND and obi > 0.20 and vwap_dev < 0.0005 and vol_surge > 1.2:
            prob_win = 0.63
            exp_gain = 0.0045   # 45 bps target
            exp_loss = 0.0020   # 20 bps stop
            ev = (prob_win * exp_gain) - ((1 - prob_win) * exp_loss) - roundtrip_cost

            if (ev * 10000) >= MIN_EXPECTED_EDGE_BPS:
                options_advice = f"BUY CALL Option | Strike: ${ceil_strike(latest.last_price)} | Target Delta: 0.65+"
                return "BUY", prob_win, ev, options_advice

        elif regime == MarketRegime.BEAR_TREND and obi < -0.20 and vwap_dev > -0.0005 and vol_surge > 1.2:
            prob_win = 0.61
            exp_gain = 0.0045
            exp_loss = 0.0020
            ev = (prob_win * exp_gain) - ((1 - prob_win) * exp_loss) - roundtrip_cost

            if (ev * 10000) >= MIN_EXPECTED_EDGE_BPS:
                options_advice = f"BUY PUT Option | Strike: ${floor_strike(latest.last_price)} | Target Delta: -0.65+"
                return "SELL", prob_win, ev, options_advice

        return "HOLD", 0.0, 0.0, None

def ceil_strike(price: float) -> float:
    return float(np.ceil(price))

def floor_strike(price: float) -> float:
    return float(np.floor(price))

# -------------------------------------------------------------------
# 4. RISK MANAGER & FRACTIONAL KELLY SIZING
# -------------------------------------------------------------------
class RiskEngine:
    def __init__(self, initial_capital: float):
        self.capital = initial_capital
        self.peak_capital = initial_capital
        self.kill_switch = False

    def validate_and_size(self, symbol: str, price: float, prob_win: float, ev: float) -> Tuple[bool, int, str]:
        if self.kill_switch:
            return False, 0, "Kill switch active due to prior max drawdown."

        # Peak Drawdown Check
        if self.capital > self.peak_capital:
            self.peak_capital = self.capital

        drawdown = (self.peak_capital - self.capital) / self.peak_capital
        if drawdown >= MAX_DRAWDOWN_PCT:
            self.kill_switch = True
            return False, 0, f"MAX DRAWDOWN EXCEEDED ({drawdown:.2%}). Emergency Kill Switch Triggered!"

        # Fractional Kelly Position Sizing (Quarter Kelly)
        b = 2.25  # Payoff ratio (45bps / 20bps)
        p = prob_win
        q = 1.0 - p
        kelly_fraction = max(0.0, (b * p - q) / b)
        quarter_kelly = kelly_fraction * 0.25

        max_alloc = self.capital * MAX_POSITION_PCT
        kelly_alloc = self.capital * quarter_kelly
        final_alloc = min(max_alloc, kelly_alloc)

        qty = max(1, int(final_alloc // price))
        return True, qty, "APPROVED"

# -------------------------------------------------------------------
# 5. ASYNC ENGINE & MANUAL COMMAND TERMINAL
# -------------------------------------------------------------------
class QuantitativeSystemCoordinator:
    def __init__(self):
        self.watchlist = load_watchlist(WATCHLIST_FILE)
        self.market_state = InMemoryMarketState()
        self.risk_engine = RiskEngine(INITIAL_CAPITAL)
        self.positions: Dict[str, int] = {}
        self.auto_trading = True

    async def on_tick(self, tick: MarketTick):
        self.market_state.push_tick(tick)
        if not self.auto_trading:
            return

        history = self.market_state.get_history(tick.symbol)
        regime = RegimeEngine.detect(history)
        action, prob_win, ev, opt_advice = AlphaEngine.evaluate_opportunity(history, regime)

        if action != "HOLD":
            approved, qty, reason = self.risk_engine.validate_and_size(
                tick.symbol, tick.last_price, prob_win, ev
            )

            if approved:
                curr_pos = self.positions.get(tick.symbol, 0)
                if action == "BUY" and curr_pos == 0:
                    self.positions[tick.symbol] = qty
                    logger.info(
                        f"⚡ [AUTO-ENTRY APPROVED] BUY {qty} shares {tick.symbol} @ ${tick.last_price:.2f} | "
                        f"Regime: {regime.value} | EV: +{ev*10000:.1f} bps | Options Signal: [{opt_advice}]"
                    )
                elif action == "SELL" and curr_pos > 0:
                    logger.info(f"⚡ [AUTO-EXIT APPROVED] Sold {curr_pos} shares of {tick.symbol} @ ${tick.last_price:.2f}")
                    self.positions[tick.symbol] = 0
            else:
                logger.warning(f"🛡️ [RISK REJECT] {tick.symbol}: {reason}")

    async def terminal_interactive_loop(self):
        """Asynchronous Interactive Terminal for real-time manual control."""
        loop = asyncio.get_event_loop()
        print("\n" + "="*65)
        print("🕹️  HIGH-CONVICTION TRADING CONTROL TERMINAL")
        print("Commands:")
        print("  buy <symbol> <qty>   -> Manual Market Buy")
        print("  sell <symbol> <qty>  -> Manual Market Sell")
        print("  toggle               -> Pause / Resume Autonomous Engine")
        print("  status               -> Display Capital & Positions")
        print("  panic                -> EMERGENCY LIQUIDATE ALL POSITIONS")
        print("="*65 + "\n")

        while True:
            cmd_input = await loop.run_in_executor(None, input, "COMMAND > ")
            parts = cmd_input.strip().split()
            if not parts:
                continue

            cmd = parts[0].lower()
            if cmd == "toggle":
                self.auto_trading = not self.auto_trading
                state_str = "ACTIVE 🟢" if self.auto_trading else "PAUSED 🔴"
                logger.info(f"--> Automated Engine State Changed to: {state_str}")

            elif cmd == "status":
                logger.info(f"Capital: ${self.risk_engine.capital:,.2f} | Open Positions: {self.positions}")

            elif cmd == "panic":
                logger.warning("🚨 EMERGENCY PANIC TRIGGERED! Clearing all positions immediately...")
                for sym, qty in list(self.positions.items()):
                    if qty > 0:
                        logger.info(f"🔥 FLUSHED {qty} shares of {sym}")
                        self.positions[sym] = 0

            elif cmd in ["buy", "sell"] and len(parts) == 3:
                sym = parts[1].upper()
                qty = int(parts[2])
                if cmd == "buy":
                    self.positions[sym] = self.positions.get(sym, 0) + qty
                    logger.info(f"📥 [MANUAL OVERRIDE] BOUGHT {qty} shares of {sym}")
                else:
                    curr = self.positions.get(sym, 0)
                    sell_amount = min(curr, qty) if curr > 0 else qty
                    self.positions[sym] = max(0, curr - sell_amount)
                    logger.info(f"📤 [MANUAL OVERRIDE] SOLD {sell_amount} shares of {sym}")

# -------------------------------------------------------------------
# 6. STREAMING FEED SIMULATOR & ENTRY POINT
# -------------------------------------------------------------------
async def mock_streaming_websocket(system: QuantitativeSystemCoordinator):
    """Simulates zero-latency WebSocket stream."""
    prices = {sym: 150.0 + np.random.uniform(10, 100) for sym in system.watchlist}

    while True:
        await asyncio.sleep(0.04)  # 40ms high-frequency tick rate
        symbol = np.random.choice(system.watchlist)
        prices[symbol] += np.random.normal(0.01, 0.12)

        tick = MarketTick(
            symbol=symbol,
            timestamp=time.time(),
            last_price=round(prices[symbol], 2),
            bid=round(prices[symbol] - 0.02, 2),
            ask=round(prices[symbol] + 0.02, 2),
            bid_size=float(np.random.randint(200, 1000)),
            ask_size=float(np.random.randint(100, 400)), # Imbalance
            volume=float(np.random.randint(100, 800))
        )
        await system.on_tick(tick)

async def main():
    system = QuantitativeSystemCoordinator()
    logger.info("Starting High-Conviction Algorithmic System...")
    logger.info(f"Active Watchlist: {system.watchlist}")

    await asyncio.gather(
        mock_streaming_websocket(system),
        system.terminal_interactive_loop()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExecution stopped.")
