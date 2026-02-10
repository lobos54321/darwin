
class MyStrategy:
    def __init__(self):
        self.balance = 1000
    
    def on_price_update(self, prices):
        # BAD STRATEGY: Always buy when RSI is high (Penalized behavior)
        return {"side": "BUY", "symbol": "BTC", "amount": 0.1, "reason": ["FOMO_BUY"]}
