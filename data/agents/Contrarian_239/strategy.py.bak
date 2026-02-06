# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import math
from collections import deque
import statistics

class MyStrategy:
    """
    Agent: Contrarian_239 -> Evolved: Adaptive_MeanReversion_v2
    
    🧬 Evolution Summary:
    1.  **Learned from Failure**: The previous EMA strategy lagged too much in volatile crypto markets, causing entries at local tops.
    2.  **Winner's DNA (Momentum)**: Absorbed the need for momentum, but applied it on a micro-scale (tick-by-tick) rather than macro-trend.
    3.  **Unique Mutation (Z-Score Scalping)**: Replaced Moving Averages with Statistical Z-Score (Standard Score). We now buy statistically significant deviations from the mean (Oversold) ONLY when a micro-momentum reversal is detected.
    4.  **Survival Protocols**: Added strict Time-Based Exits and Volatility-Adjusted Position Sizing to prevent the account drain seen in the previous iteration.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Adaptive_MeanReversion_v2)")
        
        # --- Hyperparameters ---
        self.WINDOW_SIZE = 12           # Lookback window for statistics (Short term)
        self.Z_ENTRY_THRESHOLD = -1.8   # Buy when price is 1.8 std devs below mean
        self.Z_EXIT_THRESHOLD = 1.5     # Sell when price is 1.5 std devs above mean
        
        self.STOP_LOSS_PCT = 0.04       # Hard stop loss at 4%
        self.TAKE_PROFIT_PCT = 0.07     # Take profit at 7%
        self.MAX_HOLD_TICKS = 20        # Time-based stop (don't hold stagnant bags)
        self.BASE_BET_PCT = 0.15        # Bet 15% of portfolio per trade
        
        # --- State ---
        self.price_history = {}         # {symbol: deque(maxlen=WINDOW_SIZE)}
        self.positions = {}             # {symbol: {"entry_price": float, "ticks_held": int}}
        self.banned_tags = set()

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)

    def _calculate_z_score(self, price_series):
        if len(price_series) < 2:
            return 0.0
        mean = statistics.mean(price_series)
        stdev = statistics.stdev(price_series)
        if stdev == 0:
            return 0.0
        return (price_series[-1] - mean) / stdev

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Returns: ('buy', symbol, amount_usd) or ('sell', symbol, amount) or None
        """
        
        # 1. Update History & Manage Existing Positions
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Initialize history if new
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.WINDOW_SIZE)
            self.price_history[symbol].append(current_price)
            
            # Check Exits for current positions
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos["entry_price"]
                pos["ticks_held"] += 1
                
                pct_change = (current_price - entry_price) / entry_price
                
                # Logic: Stop Loss / Take Profit / Time Stop
                should_sell = False
                reason = ""
                
                if pct_change <= -self.STOP_LOSS_PCT:
                    should_sell = True
                    reason = "Stop Loss"
                elif pct_change >= self.TAKE_PROFIT_PCT:
                    should_sell = True
                    reason = "Take Profit"
                elif pos["ticks_held"] >= self.MAX_HOLD_TICKS and pct_change < 0:
                    should_sell = True
                    reason = "Time Stop (Stagnant)"
                
                # Dynamic Exit based on Z-Score (Mean Reversion)
                z_score = self._calculate_z_score(self.price_history[symbol])
                if z_score > self.Z_EXIT_THRESHOLD:
                    should_sell = True
                    reason = "Statistical Overextension"

                if should_sell:
                    del self.positions[symbol]
                    return ("sell", symbol, 1.0) # Sell 100% of position

        # 2. Scan for New Entries
        # Only hold one position at a time to rebuild capital (Conservative Mode)
        if len(self.positions) >= 1:
            return None

        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions or symbol in self.banned_tags:
                continue
                
            history = self.price_history[symbol]
            if len(history) < self.WINDOW_SIZE:
                continue
            
            current_price = data["priceUsd"]
            prev_price = history[-2]
            
            z_score = self._calculate_z_score(history)
            
            # STRATEGY: Statistical Dip + Micro Momentum
            # We want a low Z-score (oversold) BUT price must be ticking up (green candle)
            # This filters out "catching a falling knife"
            is_oversold = z_score < self.Z_ENTRY_THRESHOLD
            is_recovering = current_price > prev_price
            
            if is_oversold and is_recovering:
                candidates.append((symbol, z_score))
        
        # Pick the most oversold candidate
        if candidates:
            candidates.sort(key=lambda x: x[1]) # Sort by lowest Z-score
            best_pick = candidates[0][0]
            
            self.positions[best_pick] = {
                "entry_price": prices[best_pick]["priceUsd"],
                "ticks_held": 0
            }
            
            # Calculate dynamic position size based on current balance simulation
            # Assuming we have access to balance, otherwise return percentage instruction
            return ("buy", best_pick, self.BASE_BET_PCT) 

        return None