import asyncio
import time
import math
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import numpy as np
import pandas as pd

# Configure Structured Auditing Log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("QUANT_ENGINE")

# -------------------------------------------------------------------
# 1. DATA TYPES & IN-MEMORY STATE
# -------------------------------------------------------------------
class MarketRegime(Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    RANGEBOUND = "RANGEBOUND"
    LIQUIDITY_CRISIS = "LIQUIDITY_CRISIS"

@dataclass
class TickData:
    symbol: str
    timestamp: float
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last_price: float
    volume: float

@dataclass
class Position:
    symbol: str
    qty: int
    entry_price: float
    unrealized_pnl: float = 0.0

# -------------------------------------------------------------------
# 2. FEATURE & MICROSTRUCTURE ENGINE
# -------------------------------------------------------------------
class QuantitativeFeatureEngine:
    """Calculates microstructure, statistical, and trend features in real time."""
    
    @staticmethod
    def compute_features(ticks: List[TickData]) -> Dict[str, float]:
        if len(ticks) < 10:
            return {}

        prices = np.array([t.last_price for t in ticks])
        volumes = np.array([t.volume for t in ticks])
        latest = ticks[-1]

        # 1. Microstructure Features
        spread = max(0.0001, latest.ask - latest.bid)
        mid_price = (latest.ask + latest.bid) / 2.0
        pct_spread = spread / mid_price
        
        # Order Book Imbalance (OBI)
        depth_denom = (latest.bid_size + latest.ask_size)
        obi = (latest.bid_size - latest.ask_size) / depth_denom if depth_denom > 0 else 0.0

        # 2. VWAP & Deviations
        pv = prices * volumes
        cum_vol = np.sum(volumes)
        vwap = np.sum(pv) / cum_vol if cum_vol > 0 else mid_price
        vwap_dev = (latest.last_price - vwap) / vwap

        # 3. Volatility (Parkinson/Standard Rolling)
        returns = np.diff(prices) / prices[:-1]
        realized_vol = np.std(returns) if len(returns) > 1 else 0.0

        # 4. Momentum & Acceleration
        ema_fast = pd.Series(prices).ewm(span=3).mean().iloc[-1]
        ema_slow = pd.Series(prices).ewm(span=10).mean().iloc[-1]
        mom_slope = (ema_fast - ema_slow) / ema_slow

        return {
            "mid_price": mid_price,
            "spread": spread,
            "pct_spread": pct_spread,
            "obi": obi,
            "vwap": vwap,
            "vwap_dev": vwap_dev,
            "realized_vol": realized_vol,
            "mom_slope": mom_slope
        }

# -------------------------------------------------------------------
# 3. REGIME DETECTION ENGINE
# -------------------------------------------------------------------
class MarketRegimeEngine:
    """Classifies real-time market regimes to adapt signal generation."""
    
    @staticmethod
    def detect_regime(features: Dict[str, float]) -> MarketRegime:
        vol = features.get("realized_vol", 0.0)
        spread = features.get("pct_spread", 0.0)
        mom = features.get("mom_slope", 0.0)

        if spread > 0.005 or vol > 0.03:  # Liquidity dry up or extreme volatility
            return MarketRegime.LIQUIDITY_CRISIS
        elif vol > 0.015:
            return MarketRegime.HIGH_VOLATILITY
        elif mom > 0.001:
            return MarketRegime.TRENDING_BULL
        elif mom < -0.001:
            return MarketRegime.TRENDING_BEAR
        else:
            return MarketRegime.RANGEBOUND

# -------------------------------------------------------------------
# 4. RISK MANAGEMENT & SAFETY ENGINE (KILL SWITCH)
# -------------------------------------------------------------------
class RiskManager:
    """Independent risk engine with full override authority and circuit breaker."""
    
    def __init__(self, max_drawdown_pct: float = 0.02, max_position_pct: float = 0.10):
        self.max_drawdown_pct = max_drawdown_pct
        self.max_position_pct = max_position_pct
        self.peak_portfolio_value = 100000.0
        self.kill_switch_triggered = False

    def validate_trade(
        self, 
        symbol: str, 
        side: str, 
        target_qty: int, 
        price: float, 
        current_portfolio_value: float,
        data_latency_ms: float
    ) -> Tuple[bool, str]:
        
        # Check Kill Switch
        if self.kill_switch_triggered:
            return False, "REJECTED: Risk Engine Kill Switch Active."

        # Check Stale Data Latency (>500ms safety limit)
        if data_latency_ms > 500:
            return False, f"REJECTED: Stale Data Latency ({data_latency_ms:.1f}ms)."

        # Check Drawdown Limit
        if current_portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = current_portfolio_value
            
        drawdown = (self.peak_portfolio_value - current_portfolio_value) / self.peak_portfolio_value
        if drawdown >= self.max_drawdown_pct:
            self.kill_switch_triggered = True
            return False, f"CRITICAL: Maximum Drawdown ({drawdown:.2%}) Exceeded! Triggering Kill Switch."

        # Check Single Position Size Limit
        order_value = target_qty * price
        if order_value > (current_portfolio_value * self.max_position_pct):
            return False, f"REJECTED: Order value ${order_value:.2f} exceeds max position limit."

        return True, "APPROVED"

# -------------------------------------------------------------------
# 5. EXPECTED EDGE & FRACTIONAL KELLY SIZING
# -------------------------------------------------------------------
class PositionSizerAndEdge:
    """Calculates cost-adjusted expected edge and fractional Kelly position size."""

    @staticmethod
    def evaluate_edge_and_size(
        features: Dict[str, float],
        regime: MarketRegime,
        portfolio_value: float,
        commission_per_share: float = 0.005
    ) -> Tuple[str, int, float]:
        """Returns: (Action: BUY/SELL/HOLD, Quantity, Calculated Expected Value)"""
        
        mid_price = features.get("mid_price", 0.0)
        spread = features.get("spread", 0.0)
        obi = features.get("obi", 0.0)
        vwap_dev = features.get("vwap_dev", 0.0)
        
        if mid_price == 0:
            return "HOLD", 0, 0.0

        # Estimated Slippage & Execution Costs
        estimated_slippage = (spread / 2.0) + (mid_price * 0.0001)
        total_roundtrip_cost = (estimated_slippage * 2) + (commission_per_share * 2)

        # Signal Alpha Generation based on Order Book Imbalance & VWAP
        prob_win = 0.50
        if regime == MarketRegime.TRENDING_BULL and obi > 0.2:
            prob_win = 0.58
        elif regime == MarketRegime.RANGEBOUND and vwap_dev < -0.002:
            prob_win = 0.55
        elif regime == MarketRegime.LIQUIDITY_CRISIS:
            return "HOLD", 0, 0.0  # Refuse to trade under illiquid regimes

        expected_gain = mid_price * 0.003   # 30 bps target
        expected_loss = mid_price * 0.002   # 20 bps stop
        
        # Expected Value (EV) calculation net of execution drag
        ev = (prob_win * expected_gain) - ((1 - prob_win) * expected_loss) - total_roundtrip_cost

        # EV Threshold Safety Margin Check
        if ev <= 0.02:  # EV must clear positive threshold after fees
            return "HOLD", 0, ev

        # Fractional Kelly Position Sizing (Quarter Kelly)
        b = expected_gain / expected_loss  # Odds ratio
        p = prob_win
        q = 1.0 - p
        kelly_fraction = max(0.0, (b * p - q) / b)
        quarter_kelly = kelly_fraction * 0.25

        capital_to_allocate = portfolio_value * quarter_kelly
        target_qty = max(1, int(capital_to_allocate // mid_price))

        action = "BUY" if (obi > 0 and vwap_dev <= 0) else "HOLD"
        return action, target_qty, ev

# -------------------------------------------------------------------
# 6. ASYNCHRONOUS SYSTEM CONTROLLER
# -------------------------------------------------------------------
class SystemEngine:
    def __init__(self):
        self.market_cache: Dict[str, List[TickData]] = {"AAPL": []}
        self.positions: Dict[str, Position] = {}
        self.portfolio_value = 100000.0
        self.risk_manager = RiskManager(max_drawdown_pct=0.02)
        
    async def process_market_tick(self, tick: TickData):
        start_time = time.perf_counter()
        
        # 1. Update In-Memory Cache
        cache = self.market_cache[tick.symbol]
        cache.append(tick)
        if len(cache) > 50:
            cache.pop(0)

        # 2. Extract Features
        features = QuantitativeFeatureEngine.compute_features(cache)
        if not features:
            return

        # 3. Classify Regime
        regime = MarketRegimeEngine.detect_regime(features)

        # 4. Evaluate Expected Value & Kelly Sizing
        action, qty, ev = PositionSizerAndEdge.evaluate_edge_and_size(
            features, regime, self.portfolio_value
        )

        if action == "HOLD":
            return

        # 5. Measure System Processing Latency
        data_latency_ms = (time.time() - tick.timestamp) * 1000.0

        # 6. Validate via Independent Risk Controls
        is_approved, reason = self.risk_manager.validate_trade(
            tick.symbol, action, qty, tick.last_price, self.portfolio_value, data_latency_ms
        )

        elapsed_us = (time.perf_counter() - start_time) * 1e6

        if is_approved:
            logger.info(
                f"⚡ [EXECUTE {action}] {qty} {tick.symbol} @ ${tick.last_price:.2f} | "
                f"EV: ${ev:.4f} | Regime: {regime.value} | Internal Latency: {elapsed_us:.1f}µs"
            )
        else:
            logger.warning(f"🛡️ [RISK BLOCKED] {tick.symbol}: {reason}")

# -------------------------------------------------------------------
# 7. MOCK STREAMING EVENT LOOP (SIMULATION)
# -------------------------------------------------------------------
async def mock_websocket_feed(engine: SystemEngine):
    """Simulates zero-latency WebSocket stream ticks."""
    base_price = 180.00
    for i in range(15):
        await asyncio.sleep(0.05)  # Simulate 50ms interval ticks
        
        # Introduce price drift & simulated book dynamics
        base_price += np.random.normal(0.05, 0.10)
        tick = TickData(
            symbol="AAPL",
            timestamp=time.time(),
            bid=round(base_price - 0.01, 2),
            ask=round(base_price + 0.01, 2),
            bid_size=float(np.random.randint(100, 1000)),
            ask_size=float(np.random.randint(100, 500)),  # OBI skew
            last_price=round(base_price, 2),
            volume=float(np.random.randint(10, 200))
        )
        await engine.process_market_tick(tick)

if __name__ == "__main__":
    logger.info("Initializing Institutional Low-Latency Trading Core...")
    system = SystemEngine()
    asyncio.run(mock_websocket_feed(system))
