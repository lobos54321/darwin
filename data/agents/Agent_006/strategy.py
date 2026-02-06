```python
# Darwin SDK - Agent_006 Strategy (Evolution: Adaptive Trend Surfer v3.0)
# 🧬 Evolution: Moving Average Crossover + Volatility Filter + Dynamic Risk Management
# 🧠 Logic: "Survival first. Ride established trends, ignore noise, lock profits dynamically."
# 🎯 Goal: Rebuild capital through high-probability setups rather than high-frequency gambling.

import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized: Agent_006 (Evolution v3.0 - TrendGuard)")
        
        # --- Configuration ---
        self.short_ma_window = 7       # Faster reaction to trends
        self.long_ma_window = 20       # Baseline for trend confirmation
        self.volatility_window = 15    # Window to measure risk
        
        # --- Risk Management ---
        self.stop_loss_pct = 0.04      # 4% Hard Stop (Wider than noise)
        self.trailing_start_pct = 0.03 # Activate trailing stop after 3% gain
        self.trailing_drop_pct = 0.015 # Sell if price drops 1.5% from peak after activation
        self.max_positions = 3         # Limit exposure
        self.trade_size = 50.0         # USD per trade (Adjust based on balance)
        
        # --- State Tracking ---
        self.history = {}              # {symbol: deque(maxlen=25)}
        self.positions = {}            # {symbol: {"entry": float, "max_price": float}}
        self.banned_tags = set()       # Penalized by Hive Mind
        self.cooldowns = {}            # {symbol: ticks_remaining}

    def on_hive_signal(self, signal: dict):
        """Adapt to Hive Mind signals."""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Strategy received penalty for: {penalize}")
            self.banned_tags.update(penalize)

    def _get_sma(self, symbol, window):
        """Calculate Simple Moving Average."""
        if symbol not in self.history or len(self.history[symbol]) < window:
            return None
        return statistics.mean(list(self.history[symbol])[-window:])

    def _get_volatility(self, symbol):
        """Calculate relative volatility (StDev / Mean)."""
        if symbol not in self.history or len(self.history[symbol]) < self.volatility_window:
            return 0.0
        prices = list(self.history[symbol])[-self.volatility_window:]
        if len(prices) < 2: return 0.0
        return statistics.stdev(prices) / statistics.mean(prices)

    def on_price_update(self, prices: dict):
        """
        Core logic loop.
        Returns: ('buy', symbol, amount) or ('sell', symbol, pct) or None
        """
        decision = None
        
        # 1. Update Data & Cooldowns
        for symbol, data in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=25)
            self.history[symbol].append(data["priceUsd"])
            
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    