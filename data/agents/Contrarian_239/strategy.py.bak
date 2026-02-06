```python
# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import math
from collections import deque

class MyStrategy:
    """
    Agent: Contrarian_239 -> Evolved: Phoenix_Trend_v4
    
    🧬 Evolution Summary:
    1.  **Survival Mode**: Drastically reduced position sizing to protect the remaining $536.
    2.  **Trend Alignment**: Shifted to a pure Trend Following model (EMA Crossover). We no longer fight the market; we surf it.
    3.  **Volatility Gating**: Added standard deviation checks to avoid buying into 'scam wicks' or extreme volatility.
    4.  **Trailing Profit**: Implemented a dynamic trailing stop that tightens as profits grow to lock in gains.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Phoenix_Trend_v4)")
        
        # --- Configuration ---
        self.EMA_FAST_WINDOW = 5
        self.EMA_SLOW_WINDOW = 15
        self.MAX_HISTORY = 20
        
        # --- Risk Management ---
        self.BASE_BET_PCT = 0.15        # Only risk 15% of balance per trade (Conservative recovery)
        self.STOP_LOSS_PCT = 0.02       # 2% Hard Stop
        self.TRAILING_START_PCT = 0.03  # Activate trailing after 3% gain
        self.TRAILING_GAP_PCT = 0.01    # 1% Trailing gap
        
        # --- State ---
        self.price_history = {}         # {symbol: deque([prices])}
        self.positions = {}             # {symbol: {'entry': float, 'high': float, 'amount': float}}
        self.banned_tags = set()
        self.balance = 536.69           # Sync with provided state (simulation tracking)

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            
        # If we get a boost signal, we might clear bans or lower thresholds (Mutation)
        if signal.get("boost"):
            self.banned_tags.clear()

    def _calculate_ema(self, prices, window):
        """Calculate Exponential Moving Average manually"""
        if not prices or len(prices) < window:
            return None
        # Use the most recent 'window' prices
        relevant_prices = list(prices)[-window:]
        multiplier = 2 / (window + 1)
        ema = relevant_prices[0]
        for price in relevant_prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Returns a decision dict or None.
        """
        decision = None
        
        # Randomly shuffle processing order to avoid bias
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            data = prices[symbol]
            current_price = data["priceUsd"]
            pct_change_24h = data.get("priceChange24h", 0)
            
            # 1. Update History
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.MAX_HISTORY)
            self.price_history[symbol].append(current_price)
            
            history = self.price_history[symbol]
            
            #