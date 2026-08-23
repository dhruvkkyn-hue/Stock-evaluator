class RiskManager:
    def __init__(self, max_risk_per_trade=0.02):
        self.max_risk = max_risk_per_trade

    def calculate_position_size(self, equity, price):
        """Fixed-fractional position sizing."""
        if price <= 0: return 0
        dollar_to_invest = equity * self.max_risk
        qty = int(dollar_to_invest / price)
        return max(qty, 1)

    def validate_execution(self, symbol, side, qty, current_positions):
        """Prevents duplicate entries for the same symbol."""
        for p in current_positions:
            if p.symbol == symbol:
                return False, "Already in position"
        return True, "Safe to execute"
