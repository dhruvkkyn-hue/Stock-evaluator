class RiskManager:
    def __init__(self, risk_per_trade_pct=0.02):
        self.risk_pct = risk_per_trade_pct

    def calculate_qty(self, equity, price):
        if price <= 0: return 0
        # Calculate quantity based on 2% equity risk
        target_spend = equity * self.risk_pct
        qty = int(target_spend / price)
        return max(qty, 1)

    def is_safe_to_trade(self, symbol, current_positions):
        # Don't enter if already in a position for this symbol
        for p in current_positions:
            if p.symbol == symbol:
                return False
        return True
