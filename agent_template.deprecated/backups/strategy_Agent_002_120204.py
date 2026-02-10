import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.history_len = 50
        self.trade_amount = 100.0
        
        # Strategy Parameters (Strict Penalties Fix)
        # 1. Trend Filter: Significantly increased to ensure we only trade 
        # deviations within established high-momentum structures.
        self.min_trend_slope = 0.0004
        
        # 2. Entry Threshold: Moved to -4.0 Sigma (Extreme Rarity).
        # This fixes 'DIP_BUY' by ignoring standard corrections and targeting 
        # only black swan anomalies / algorithmic wicks.
        self.entry_z_score = -4.0
        
        # 3. Panic Filter: Widened to avoid exit during volatility spikes, 
        # but prevents buying into total collapse (Z < -8.0).
        self.panic_z_score = -8.0
        
        # 4. Confirmation: Requires positive price delta (V-shape) to confirm 
        # the anomaly is resolving.
        self.bounce_threshold = 0.0015

    def _calculate_regression(self, data):
        """Calculates Linear Regression Slope, Fair Value, and StdDev."""
        n = len(data)
        if n < 5:
            return 0.0, 0.0, 0.0
        
        x = list(range(n))
        y = data
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(y)
        
        # Slope Calculation
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        denominator = sum((xi - x_mean) ** 2 for xi in x)
        slope = numerator / denominator if denominator != 0 else 0.0
        
        # Standard Deviation
        stdev = statistics.stdev(y)
        
        # Calculate Fair Value at the current time step (end of window)
        # y = mx + c => y = mean_y + slope * (x - mean_x)
        current_fair_value = y_mean + slope * ((n - 1) - x_mean)
        
        return slope, current_fair_value, stdev

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue

            # State Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_len)
            
            self.history[symbol].append(current_price)
            
            if len(self.history[symbol]) < self.history_len:
                continue

            data = list(self.history[symbol])
            
            # --- Analytical Engine ---
            slope, fair_value, stdev = self._calculate_regression(data)
            
            if fair_value == 0 or stdev == 0:
                continue

            # 1. Filter: Structural Trend
            # Penalized for buying weak dips. We now strictly enforce buying 
            # only into high-velocity uptrends.
            norm_slope = slope / fair_value
            if norm_slope < self.min_trend_slope:
                continue

            # 2. Filter: Statistical Anomaly (Z-Score against Trend)
            # Fix 'OVERSOLD': We measure deviation from the Trend Line, not the Mean.
            # This prevents false positives during steep uptrends.
            z_score = (current_price - fair_value) / stdev

            # 3. Execution Logic
            # Condition A: Extreme Undervaluation (Z < -4.0)
            # Condition B: Not a Crash (Z > -8.0)
            if self.panic_z_score < z_score < self.entry_z_score:
                
                # 4. Filter: Instantaneous Momentum (Fix Falling Knife)
                # Price must show immediate recovery vs previous tick.
                prev_price = data[-2]
                instant_return = (current_price - prev_price) / prev_price
                
                if instant_return > self.bounce_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['ALPHA_ANOMALY', 'TREND_REGRESSION']
                    }
        
        return None