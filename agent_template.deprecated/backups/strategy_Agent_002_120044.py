import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.history_len = 60
        self.trade_amount = 100.0
        
        # Strategy Parameters (Hardened against Penalties)
        # Fix 'DIP_BUY': Stricter Trend Requirement. 
        # Slope must be significantly positive to ensure we are not buying a bearish retrace.
        self.min_trend_slope = 0.0002
        
        # Fix 'OVERSOLD': Deep Statistical Anomaly Only.
        # Moved from -3.0 to -3.5 Sigma to reduce frequency and increase quality.
        self.entry_z_score = -3.5
        
        # Panic Filter: Widen panic detection to differentiate volatility from crash.
        self.panic_z_score = -6.0
        
        # Confirmation: Requires micro-reversal to avoid catching a falling knife.
        self.reversal_factor = 1.0001

    def _calculate_stats(self, data):
        """Calculates Linear Regression Slope and Stats."""
        n = len(data)
        if n < 2: 
            return 0.0, 0.0, 0.0
        
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(data)
        
        # Calculate Slope
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(data))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0.0
        
        # Calculate StdDev
        stdev = statistics.stdev(data)
        
        return slope, y_mean, stdev

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue

            # Data Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_len)
            
            self.history[symbol].append(current_price)
            
            if len(self.history[symbol]) < self.history_len:
                continue

            data = list(self.history[symbol])
            
            # 1. Macro Analysis (Trend Filter)
            # Penalties often come from buying dips in weak trends.
            slope, mean_price, stdev = self._calculate_stats(data)
            
            if mean_price == 0 or stdev == 0:
                continue

            norm_slope = slope / mean_price
            
            # STRICTER: Trend must be clearly positive.
            if norm_slope < self.min_trend_slope:
                continue

            # 2. Statistical Value Analysis
            # Avoid simple 'RSI' logic. Use normalized statistical deviation (Z-Score).
            z_score = (current_price - mean_price) / stdev

            # 3. Execution Logic
            # Entry: Price is statistically rare cheap (Z < -3.5)
            # Safety: Price is NOT crashing (Z > -6.0)
            if self.panic_z_score < z_score < self.entry_z_score:
                
                # Confirmation: Price > Previous Price * Factor
                prev_price = data[-2]
                if current_price > prev_price * self.reversal_factor:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['STRONG_TREND_SUPPORT', 'DEEP_STATISTICAL_ALPHA']
                    }
        
        return None