import os

# System Execution Limits
INITIAL_CAPITAL = 100,000.0
MAX_DRAWDOWN_PCT = 0.02          # 2% Max Drawdown Circuit Breaker
MAX_POSITION_PCT = 0.10          # Max 10% capital in a single trade
MIN_EXPECTED_EDGE_BPS = 8.0      # Must have at least 8 bps EV net of costs

# Options / Equity Slippage & Fee Models
COMMISSION_PER_SHARE = 0.005     # $0.005 / share
ESTIMATED_SLIPPAGE_BPS = 0.0002  # 2 bps estimated market impact

# Watchlist File Location
WATCHLIST_FILE = "watchlist.txt"
AUDIT_LOG_FILE = "audit_log.txt"
