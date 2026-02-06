```python
# Darwin SDK - Agent_006 Strategy (Evolution: Darwin's Razor v4.0)
# 🧬 Evolution: Trend Following + Volatility Filter + Strict Risk Control
# 🧠 Logic: "Simplicity is the ultimate sophistication. Ride trends, cut losses fast."
# 🎯 Goal: Stable growth with reduced drawdown probability via dynamic trailing stops.

import random
from collections import deque
from statistics import mean

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized: Darwin's Razor v4.0")
        
        # --- Configuration ---
        self.history_len = 20           # Number of price points to keep in memory
        self.short_window = 5           # Short Moving Average window (Fast)
        self.long_window = 15           # Long Moving Average window (Slow)
        
        # --- Risk Management (Survival First) ---
        self.stop_loss_pct = 0.03       # 3% Hard Stop Loss (Tighter than before)
        self.take_profit_activation = 0.05 # Activate trailing stop after 5% gain
        self.trailing_deviation = 0.02  # Trail price by 2% once activated
        self.allocation_per_trade = 0.25 # Invest 25% of balance per trade to allow diversification
        
        # --- State Tracking ---
        self.price_history = {}         # {symbol: deque(maxlen=history_len)}
        self.positions = {}             # {symbol: {"entry_price": float, "highest_price": float, "trailing_active": bool}}
        self.banned_tags = set()        # Tags penalized by Hive Mind

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind regarding asset tags"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Penalized tags received: {penalize}")
            self.banned_tags.update(penalize)
            
        # Boost signals could be added here to increase allocation dynamically
        # For now, we prioritize survival (avoiding penalties)

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Returns a decision dict: {"symbol": "MOLT", "action": "buy", "amount": 0.25}
        """
        decision = None
        
        # 1. Update History & Indicators for all symbols
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Initialize history if new symbol
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.history_len)
            
            self.price_history[symbol].append(current_price)
            
            # --- Priority 1: Manage Open Positions (Exit Logic) ---
            if symbol in self.positions:
                decision = self._check_exit(symbol, current_price)
                if decision:
                    return decision # Execute exit immediately to protect capital
        
        # 2. Scan for New Entries (if no exit triggered)
        best_setup = None
        highest_momentum = -999
        
        for symbol, data in prices.items():
            # Skip if we already hold it or if it's banned
            if symbol in self.positions:
                continue
                
            # Check tags (avoid penalized assets)
            tags = data.get("tags", [])
            if any(