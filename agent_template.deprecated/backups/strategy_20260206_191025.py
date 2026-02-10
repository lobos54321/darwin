"""
Improved Strategy Implementation for Darwin SDK - Agent_006 Iteration.

Analysis & Improvements:
1.  **Regime Alignment**: The winner data (DIP_BUY, OVERSOLD) confirms a Mean Reversion regime. I have removed the 'Breakout/Pump' logic as it likely traps the bot at local tops.
2.  **Volatility Adaptation**: Replaced fixed percentage thresholds (e.g., 0.985) with Bollinger Band logic (Z-Score). This adapts the "Dip" definition to current market volatility (Standard Deviation).
3.  **Dynamic Targets**: Take Profit and Stop Loss are now calculated based on the volatility width (ATR-like logic using StdDev), rather than fixed percentages.
4.  **Smart Randomness**: Kept 'RANDOM_TEST' but added a volatility filter to avoid random trades in dead markets (eating fees).

Technique: Bollinger Bands Mean Reversion + Volatility Scaled Risk.
"""

import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Bollinger Mean Reversion v3.0)")
        self.last_prices = {}
        # Stores price history: {symbol: deque(maxlen=30)} - Increased window for better StdDev
        self.history = {} 
        self.banned_tags = set() 
        
        # --- Strategy Parameters ---
        self.history_window = 30      # Look back approx 90s (30 * 3s) for statistical significance
        self.z_score_entry = -2.0     # Buy if price is 2 StdDev below Mean (Bollinger Lower Band)
        self.risk_per_trade = 20.0    # Increased base size for high probability setups
        self.min_volatility = 0.0005  # Filter out flat markets to avoid fee churn

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            
        boost = signal.get("boost", [])
        if boost:
            # If Hive Mind suggests OVERSOLD is working, we adhere to strict reversion
            if "OVERSOLD" in boost:
                self.z_score_entry = -1.8 # Slightly more aggressive entry

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Implements Bollinger Band Mean Reversion.
        """
        decision = None
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Initialize history
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            
            self.history[symbol].append(current_price)
            self.last_prices[symbol] = current_price
            
            # Require minimum data for Standard Deviation calculation
            if len(self.history[symbol]) < 10:
                continue

            # --- Statistical Calculations (Bollinger Logic) ---
            sma = statistics.mean(self.history[symbol])
            stdev = statistics.stdev(self.history[symbol])
            
            # Avoid division by zero in extremely flat markets
            if stdev == 0:
                continue

            # Z-Score: How many standard deviations is price away from mean?
            # Negative = Below SMA, Positive = Above SMA
            z_score = (current_price - sma) / stdev
            
            # Relative Volatility (Coefficient of Variation)
            volatility_ratio = stdev / sma
            
            # --- Decision Logic ---

            # 1. 深度均值回归 (Bollinger Lower Band Reversion) - ⭐️ 赢家策略优化
            # Logic: Buy when price pierces the lower 2.0 StdDev band
            if z_score < self.z_score_entry:
                
                # Dynamic Sizing: Buy more if the deviation is extreme (e.g. -3.0 sigma)
                # Cap aggression at 2.0x
                aggression = min(2.0, abs(z_score) / 2.0) 
                amount = self.risk_per_trade * aggression
                
                # Dynamic TP/SL based on volatility width
                # If vol is high, aim for higher TP.
                tp_price = sma # Target return to mean
                sl_price = current_price - (stdev * 1.5) # Stop loss allows some wick room
                
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": round(amount, 2),
                    "reason": ["DIP_BUY", "OVERSOLD", "BOLLINGER_REVERSION"],
                    "take_profit": tp_price,
                    "stop_loss": sl_price
                }

            # 2. 随机探索 (Smart Exploration)
            # Logic: Keep random tests (as per Winner's DNA) but only if market is moving.
            # Don't trade randomly in flat markets (volatility < 0.05%).
            elif random.random() < 0.02 and volatility_ratio > self.min_volatility:
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": 5.0, # Small test amount
                    "reason": ["RANDOM_TEST"],
                    # Wide bands for random trades
                    "take_profit": current_price * 1.05,
                    "stop_loss": current_price * 0.95
                }

            if decision:
                # 🛑 HIVE MIND CHECK
                tags = decision.get("reason", [])
                if any(tag in self.banned_tags for tag in tags):
                    return None
                
                return decision
                
        return None

    def get_council_message(self, is_winner: bool) -> str:
        """
        Called during Council phase.
        """
        if is_winner:
            return "Bollinger Band logic successful. Z-Score based entries adapt better to volatility than fixed %."
        else:
            return "Mean reversion failed. Market might be trending strongly. Considering adding ADX filter to pause dips."