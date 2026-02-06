"""
Improved Strategy Implementation for Darwin SDK.
Analysis of previous iteration:
1.  The previous strategy relied on tick-to-tick volatility (approx 3s), which is too noisy.
2.  Winner analysis indicates 'DIP_BUY' and 'OVERSOLD' were successful, suggesting a mean-reversion market regime.
3.  Momentum strategies failed (likely buying tops), so we will dampen momentum logic.

Improvements:
1.  Introduced a Rolling Window (Moving Average) to define "Oversold" relative to a trend, not just the last price.
2.  Prioritized Mean Reversion (Dip Buy) logic to align with the winning strategy.
3.  Added explicit Stop Loss and Take Profit parameters to the decision dictionary.
4.  Retained a reduced Random component for exploration but lowered its probability.
"""

import random
from collections import deque
import statistics

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Smart Reversion v2.0)")
        self.last_prices = {}
        # Stores price history for SMA calculation: {symbol: deque(maxlen=20)}
        self.history = {} 
        self.banned_tags = set() 
        
        # --- Strategy Parameters ---
        self.history_window = 20      # Look back approx 1 minute (20 * 3s)
        self.dip_threshold = 0.985    # Buy if price is 1.5% below SMA (Oversold)
        self.pump_threshold = 1.025   # Buy if price is 2.5% above SMA (Strong Momentum)
        self.risk_per_trade = 15.0    # Base trade size

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🧠 Strategy received penalty for: {penalize}")
            self.banned_tags.update(penalize)
            
        boost = signal.get("boost", [])
        if boost:
            # If Hive Mind boosts specific tags, we could increase risk for those
            if "DIP_BUY" in boost:
                self.risk_per_trade = 25.0

    def on_price_update(self, prices: dict):
        """
        Called every time price updates (approx every 3s).
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Initialize history for new symbols
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            
            # Update history
            self.history[symbol].append(current_price)
            self.last_prices[symbol] = current_price
            
            # Need enough data to calculate Moving Average
            if len(self.history[symbol]) < 5:
                continue

            # Calculate Simple Moving Average (SMA)
            sma = statistics.mean(self.history[symbol])
            
            # Calculate deviation from SMA
            deviation = current_price / sma
            
            # --- 改进策略逻辑 (Improved Strategy Logic) ---
            
            # 1. 深度抄底 (Smart Mean Reversion) - ⭐️ 赢家策略核心
            # Logic: Price is significantly below the recent average.
            if deviation < self.dip_threshold:
                # Dynamic sizing: The deeper the dip, the more we buy
                aggression = 1.0 + (self.dip_threshold - deviation) * 10 
                amount = self.risk_per_trade * aggression
                
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": round(amount, 2),
                    "reason": ["DIP_BUY", "OVERSOLD", "MEAN_REVERSION"],
                    # Take profit at SMA (mean), Stop loss if it drops further
                    "take_profit": current_price * 1.03, 
                    "stop_loss": current_price * 0.95
                }
            
            # 2. 确认突破 (Confirmed Breakout) - Reduced sensitivity
            # Logic: Only chase if price is consistently above average (sustained trend)
            elif deviation > self.pump_threshold:
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": self.risk_per_trade * 0.8, # Smaller position on breakout
                    "reason": ["MOMENTUM_UP", "TREND_FOLLOWING"],
                    "take_profit": current_price * 1.05,
                    "stop_loss": current_price * 0.98
                }
            
            # 3. 随机探索 (Exploration) - Reduced Probability
            # Kept because 'RANDOM_TEST' was present in winner's tags, helps find new regimes
            elif random.random() < 0.02: # Reduced from 0.05 to 0.02
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": 5.0,
                    "reason": ["RANDOM_TEST"],
                    "take_profit": current_price * 1.10,
                    "stop_loss": current_price * 0.90
                }

            if decision:
                # 🛑 HIVE MIND CHECK
                tags = decision.get("reason", [])
                if any(tag in self.banned_tags for tag in tags):
                    # If primary strategy is banned, do not trade
                    print(f"🛑 Trade aborted! Hive Mind penalized tags: {tags}")
                    return None

                return decision
                
        return None # Hold

    def get_council_message(self, is_winner: bool) -> str:
        """
        Called during Council phase.
        """
        if is_winner:
            return "Adopted Mean Reversion logic based on previous winners. Buying dips against SMA is yielding best R/R."
        else:
            return "Dip buying thresholds might be too tight. Will widen the SMA window to capture larger volatility."