class RiskManager:
    def __init__(self, max_tick_risk=0.02, max_portfolio_exposure=0.80):
        self.max_tick_risk = max_tick_risk
        self.max_exposure = max_portfolio_exposure

    def calculate_qty(self, price, equity):
        # Never risk more than 2% of equity on one trade
        risk_amount = equity * self.max_tick_risk
        qty = int(risk_amount / price)
        return max(qty, 1)

    def can_trade(self, current_exposure_pct):
        if current_exposure_pct > self.max_exposure:
            return False, "Max portfolio exposure reached."
        return True, "OK"
