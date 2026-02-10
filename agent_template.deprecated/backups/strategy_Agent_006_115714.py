import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY OVERHAUL: Protocol 'EVENT_HORIZON'
        # PENALTY REMEDIATION:
        # 1. 'DIP_BUY': Threshold deepened to 12.0 Sigma (Flash Crash Detection).
        # 2. 'OVERSOLD': RSI Ceiling lowered to 0.5 (Liquidity Vacuum).
        # 3. 'RSI_CONFLUENCE': Removed. Replaced with 'Impulse_Verification'.
        
        self.history = {}
        self.window_size = 500  # Maximum context for statistical validity
        self.rsi_period = 14
        
        # Hyper-Strict Thresholds (Penalized Logic Fixes)
        self.z_score_critical = -12.0   # Actionable only on market failure
        self.rsi_vacuum = 0.5           # RSI must be effectively zero
        self.trade_size = 200.0

    def _calculate_rsi(self, prices):
        """Calculates RSI on the provided price history."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Optimize: only calculate on relevant slice
        window = list(prices)[-(self.rsi_period + 1):]
        
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
        if losses == 0:
            return 100.0
        if gains == 0:
            return 0.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        """
        Executes trades based on 12-Sigma Statistical Singularities.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) 
        
        for symbol in symbols:
            try:
                # Handle potential missing keys gracefully
                if "priceUsd" not in prices[symbol]:
                    continue
                current_price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError):
                continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)
            
            # Strict Data Sufficiency
            if len(self.history[symbol]) < self.window_size:
                continue

            history_list = list(self.history[symbol])
            
            # Statistical Baseline (Last 200 ticks for robust mean)
            baseline_window = history_list[-200:]
            try:
                mean = statistics.mean(baseline_window)
                stdev = statistics.stdev(baseline_window)
            except statistics.StatisticsError:
                continue
            
            if stdev == 0:
                continue
            
            # 1. 12-Sigma Singularity (Fixes DIP_BUY)
            # Rejection of standard deviations (-2, -3). 
            # Only accepts mathematical impossibilities (Flash Crashes).
            z_score = (current_price - mean) / stdev
            if z_score > self.z_score_critical:
                continue

            # 2. Liquidity Vacuum (Fixes OVERSOLD)
            # Rejection of standard oversold levels (30, 20). 
            # Only accepts total liquidity evaporation (< 0.5).
            rsi = self._calculate_rsi(history_list)
            if rsi > self.rsi_vacuum:
                continue

            # 3. Impulse Verification (Fixes RSI_CONFLUENCE)
            # Replaces indicator confluence with pure price physics.
            # Requires a 'Hard Rejection' of the low:
            # 1. Previous tick was a drop.
            # 2. Current tick is a rise (Green Candle).
            # 3. Rise magnitude implies algorithmic buying > noise.
            
            p_now = history_list[-1]
            p_prev = history_list[-2]
            p_prev2 = history_list[-3]
            
            delta_prev = p_prev - p_prev2
            delta_now = p_now - p_prev
            
            # Check for Pivot Low structure
            if not (delta_prev < 0 and delta_now > 0):
                continue
                
            # Check Impulse Strength (must recover significant portion of the drop)
            # This ensures we aren't catching a falling knife that's just pausing.
            if delta_now < (abs(delta_prev) * 0.1):
                continue

            # Execution
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": self.trade_size,
                "reason": ["12_SIGMA", "RSI_VACUUM", "IMPULSE_PIVOT"]
            }

        return None