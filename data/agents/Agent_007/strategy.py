# Darwin SDK - User Strategy Template
# 🧠 AGENT 007: THE CHASER (MOMENTUM ONLY)

import random

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (The Chaser v1.0)")
        self.last_prices = {}
        self.banned_tags = set()

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🧠 Strategy received penalty for: {penalize}")
            self.banned_tags.update(penalize)

    def on_price_update(self, prices: dict):
        decision = None
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            last_price = self.last_prices.get(symbol, current_price)
            
            # Calculate % change since last update
            pct_change = ((current_price - last_price) / last_price) * 100 if last_price > 0 else 0
            
            # 1. 激进追涨 (Momentum): 只要有一点上涨就追
            if pct_change > 0.1: # Threshold lowered to 0.1%
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": 15.0,
                    "reason": ["MOMENTUM_UP", "AGGRESSIVE_CHASE"]
                }

            self.last_prices[symbol] = current_price
            
            if decision:
                # 🛑 HIVE MIND CHECK
                tags = decision.get("reason", [])
                if any(tag in self.banned_tags for tag in tags):
                    print(f"🛑 Trade aborted! Hive Mind penalized tags: {tags}")
                    return None
                return decision
                
        return None
