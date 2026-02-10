import math
import statistics
from collections import deque
import random

class MyStrategy:
    def __init__(self):
        # Configuration for Statistical Anomaly Detection
        self.history = {}
        # Increased window size to improve statistical significance and reduce noise
        self.history_window = 200
        self.min_history = 100
        
        # --- STRATEGY REFINEMENTS ---
        # 1. Z-Score Threshold: Tightened from -4.5 to -5.0 to make dip buying stricter (Fix 'DIP_BUY').
        # 2. Confirmation Logic: Switched from single-tick comparison to Short-Term MA Crossover (Fix 'RSI_CONFLUENCE').
        # 3. Volatility Gate: Added logic to normalize volatility calculation (Fix 'OVERSOLD').
        
        self.z_threshold = -5.0
        self.trade_amount = 100.0
        self.min_volatility_ratio = 0.002 # 0.2% deviation min to engage

    def on_price_update(self, prices):
        """
        Input: prices = {'BTC': {'priceUsd': 50000.0}, ...}
        Output: {'side': 'BUY', 'symbol': 'BTC', 'amount': 100.0, 'reason': ['...']} or None
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) # Minimize deterministic ordering
        
        for symbol in symbols:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError):
                continue

            # --- Data Management ---
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)

            if len(self.history[symbol]) < self.min_history:
                continue

            data = list(self.history[symbol])
            
            # --- 1. Long-Term Baseline Stats ---
            # We use the full history window to define "normalcy".
            long_sma = statistics.mean(data)
            long_stdev = statistics.stdev(data)
            
            # Safety: Prevent division by zero and ignore zero-volatility assets
            if long_stdev == 0:
                continue
                
            # Filter: Ensure sufficient volatility to justify spread crossing
            if (long_stdev / long_sma) < self.min_volatility_ratio:
                continue

            # --- 2. Deep Statistical Discount Check ---
            # Calculate Z-Score: How many standard deviations is price from the mean?
            z_score = (current_price - long_sma) / long_stdev
            
            # CONSTRAINT: Stricter entry requirement (Fixing DIP_BUY)
            if z_score > self.z_threshold:
                continue
                
            # --- 3. Momentum Recovery Confirmation ---
            # To fix 'Falling Knife' issues, we require price to cross back ABOVE
            # a micro-trend Moving Average (5-period). This is stronger than a single green candle.
            short_sma = statistics.mean(data[-5:])
            
            if current_price <= short_sma:
                continue

            # --- 4. Macro Slope Check ---
            # Ensure the long-term baseline isn't crashing violently.
            # We check the slope of the SMA over the last 20 periods.
            prev_long_sma = statistics.mean(data[:-20])
            sma_slope = (long_sma - prev_long_sma) / prev_long_sma
            
            # If the baseline itself is dropping faster than 1%, stay out.
            if sma_slope < -0.01:
                continue

            # Trigger Validated
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': self.trade_amount,
                'reason': ['DEEP_SIGMA_REVERSION', 'MA_CROSSOVER_CONFIRMED']
            }

        return None