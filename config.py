# config.py
import numpy as np

CONFIG = {
    "initial_capital": 100000,
    "symbols": ["AAPL", "MSFT", "TSLA", "NVDA", "AMD"],
    "timeframe": "5Min",
    "risk": {
        "max_drawdown_limit": 0.15,
        "max_daily_loss": 0.02,
        "max_participation_rate": 0.1,  # Can't trade more than 10% of bar volume
        "slippage_bps": 2.0,            # 2 basis points
        "commissions_per_share": 0.005
    },
    "wfo": {
        "train_months": 6,
        "val_months": 1,
        "holdout_months": 3
    },
    "param_grid": {
        "ema_fast": [9, 12, 20],
        "ema_slow": [21, 50, 100],
        "rsi_period": [14],
        "vwap_dist": [0.0, 0.001] # Distance from VWAP to trigger
    }
}
