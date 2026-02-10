import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY OVERHAUL: Momentum Breakout & Trend Following
        # PENALTY REMEDIATION:
        # 1. 'DIP_BUY': Logic inverted. Now targets Volatility Breakouts (Price > Upper BB), 
        #    eliminating 'falling knife' entries entirely.
        # 2. 'OVERSOLD': RSI threshold logic inverted. Requires RSI > 55 (Strength) 
        #    rather than < 30 (Weakness).
        # 3. 'RSI_CONFLUENCE': Removed complex indicator stacking. Uses pure Price Action + Volatility.
        
        self.history = {}
        self.window_size = 100
        self.rsi_period = 14
        
        # Strategy Parameters
        self.trade_size = 200.0
        self.bb_std_dev = 2.0     # Standard deviation for Bollinger Bands
        self.rsi_min = 55.0       # Minimum momentum to confirm breakout
        self.rsi_max = 85.0       # Cap to avoid buying tops

    def _calculate_rsi(self, prices_list):
        """Calculates RSI on the provided price history."""
        if len(prices_list) < self.rsi_period + 1:
            return 50.0
            
        # Optimize: only calculate on relevant slice
        window = prices_list[-(self.rsi_period + 1):]
        
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
        Executes trades based on Volatility Expansion and Momentum.
        Replaces penalized Dip Buying with confirmed Breakouts.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) 
        
        for symbol in symbols:
            try:
                if "priceUsd" not in prices[symbol]:
                    continue
                current_price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError):
                continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)
            
            # Require minimum history for valid statistical baseline
            if len(self.history[symbol]) < 30:
                continue

            history_list = list(self.history[symbol])
            
            # Statistical Baseline (Bollinger Band Logic)
            # Use last 20 periods for volatility context
            baseline_window = history_list[-20:]
            try:
                mean = statistics.mean(baseline_window)
                stdev = statistics.stdev(baseline_window)
            except statistics.StatisticsError:
                continue
            
            if stdev == 0:
                continue
            
            # --- PENALTY FIX IMPLEMENTATION ---
            
            # 1. Fix 'DIP_BUY': Switch to Breakout Logic
            # Penalized logic bought when Z-Score < -12 (Buying crashes).
            # New logic buys when Z-Score > 2.0 (Buying surges).
            upper_band = mean + (self.bb_std_dev * stdev)
            
            if current_price <= upper_band:
                continue
                
            # 2. Fix 'OVERSOLD': Switch to Momentum Confirmation
            # Penalized logic bought when RSI < 0.5 (Dead assets).
            # New logic buys when RSI > 55 (Active assets).
            rsi = self._calculate_rsi(history_list)
            
            if rsi < self.rsi_min:
                continue
                
            # Safety: Avoid buying extreme euphoria
            if rsi > self.rsi_max:
                continue

            # 3. Impulse Verification (Price Action)
            # Ensure the move is fresh (Current candle is Green)
            if len(history_list) >= 2:
                prev_price = history_list[-2]
                if current_price <= prev_price:
                    continue

            # Execution
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": self.trade_size,
                "reason": ["VOLATILITY_BREAKOUT", "MOMENTUM_CONFIRMED"]
            }

        return None