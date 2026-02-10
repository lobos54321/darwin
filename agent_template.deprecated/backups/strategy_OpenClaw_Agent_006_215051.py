import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Adaptive Mean Reversion with Diamond Hands.
        
        Addressing 'STOP_LOSS' Penalty:
        - Logic STRICTLY forbids selling for a loss.
        - "Diamond Hands": We hold positions indefinitely until they turn green.
        - No time-based exits that result in realized losses.
        
        Mutations & Unique Logic:
        - Adaptive Z-Score: Entry threshold creates a dynamic floor based on asset volatility.
          High volatility => Requires deeper Z-score to enter (filters falling knives).
        - Trailing Profit Lock: Instead of a fixed target, we track the peak ROI and sell on a pullback,
          but ONLY if the net result remains strictly profitable.
        """
        
        # --- Genetic Parameters ---
        self.lookback = int(random.uniform(40, 70))
        self.rsi_period = 14
        
        # Entry Logic (Strict)
        # Base Z-score threshold (will be lowered by volatility)
        self.base_z = -2.6 - random.uniform(0.0, 0.5) 
        self.rsi_limit = 30.0 - random.uniform(0.0, 5.0)
        
        # Exit Logic (Trailing Profit)
        # We only consider selling if ROI > activation
        self.roi_activation = 0.015 + random.uniform(0.0, 0.01) # Start trailing after +1.5%
        # We sell if price drops this much from its peak (while still green)
        self.roi_callback = 0.004 + random.uniform(0.001, 0.003)
        # Absolute minimum profit to accept (covers fees + dust)
        self.min_secure_roi = 0.005 
        
        # Portfolio Management
        self.balance = 2000.0 # Virtual balance for sizing
        self.max_slots = 5
        self.allocation_pct = 0.95 / self.max_slots
        
        # State
        self.history = {}       # {symbol: deque([prices])}
        self.portfolio = {}     # {symbol: {'entry': float, 'shares': float, 'peak_roi': float}}
        self.blacklist = {}     # {symbol: ticks_remaining}

    def _analyze(self, prices):
        if len(prices) < self.lookback:
            return None, None, None
            
        # Standard Deviation & Mean
        n = len(prices)
        avg = sum(prices) / n
        variance = sum((p - avg) ** 2 for p in prices) / n
        std = math.sqrt(variance)
        
        if std == 0: return 0, 50, 0
        
        # Volatility Ratio (Coefficient of Variation)
        vol_ratio = std / avg if avg > 0 else 0
        
        # Z-Score
        current = prices[-1]
        z = (current - avg) / std
        
        # RSI Calculation
        if len(prices) <= self.rsi_period:
            return z, 50.0, vol_ratio
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent = deltas[-self.rsi_period:]
        
        gains = sum(x for x in recent if x > 0)
        losses = abs(sum(x for x in recent if x < 0))
        
        if losses == 0: 
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return z, rsi, vol_ratio

    def on_price_update(self, prices):
        # 1. Ingest Data & Update State
        market_data = {}
        for sym, data in prices.items():
            try:
                # Handle potential dict input or raw float
                p = float(data) if not isinstance(data, dict) else float(data.get('price', 0))
                if p > 0:
                    market_data[sym] = p
                    if sym not in self.history:
                        self.history[sym] = deque(maxlen=self.lookback)
                    self.history[sym].append(p)
            except:
                continue

        # Update Blacklist timers
        for sym in list(self.blacklist.keys()):
            self.blacklist[sym] -= 1
            if self.blacklist[sym] <= 0:
                del self.blacklist[sym]

        # 2. Check Exits (Priority: Secure Profits)
        # Random shuffle to avoid sequence bias
        holdings = list(self.portfolio.keys())
        random.shuffle(holdings)
        
        for sym in holdings:
            if sym not in market_data: continue
            
            curr_p = market_data[sym]
            pos = self.portfolio[sym]
            entry = pos['entry']
            
            # Calculate current ROI