import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Data window settings
        self.history = {}
        self.history_len = 60
        self.trade_amount = 100.0
        
        # Strategy Parameters (Stricter to avoid Penalties)
        # Fix 'DIP_BUY': Only buy dips in confirmed uptrends.
        self.min_trend_slope = 0.0001 
        
        # Fix 'OVERSOLD': Use Deep Statistical Deviation (3 Sigma) instead of shallow bands.
        self.z_score_buy = -3.0
        
        # Panic Filter: Avoid buying if price is crashing too violently (falling knife).
        self.z_score_panic = -5.0 

    def _calculate_slope(self, series):
        """Calculates Linear Regression Slope."""
        n = len(series)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(series)
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(series))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        return numerator / denominator if denominator != 0 else 0.0

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError):
                continue

            # Data Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_len)
            self.history[symbol].append(current_price)

            if len(self.history[symbol]) < self.history_len:
                continue

            data = list(self.history[symbol])
            
            # 1. Trend Filter (Fixing DIP_BUY)
            # Calculate slope of the full window to determine Macro Trend.
            # Rule: NEVER buy a dip if the macro trend is negative or flat.
            slope = self._calculate_slope(data)
            
            # Normalize slope by price to make it percentage-based relative to price
            normalized_slope = slope / data[0]
            if normalized_slope < self.min_trend_slope:
                continue

            # 2. Statistical Analysis (Fixing OVERSOLD/RSI_CONFLUENCE)
            # Use Z-Score to find statistical anomalies relative to recent volatility.
            # Using a shorter window for local deviation against the macro trend.
            local_window = data[-20:]
            local_mean = statistics.mean(local_window)
            local_stdev = statistics.stdev(local_window)

            if local_stdev == 0:
                continue

            z_score = (current_price - local_mean) / local_stdev

            # 3. Execution Logic
            # Buy Condition:
            # - Price is statistically cheap (Z < -3.0)
            # - But NOT in freefall (Z > -5.0) -> "Panic Filter"
            # - Momentum Check: Current price > Last price (Micro-reversal confirmation)
            if self.z_score_panic < z_score < self.z_score_buy:
                # Instantaneous momentum check to avoid catching the exact bottom tick (risky)
                if current_price > data[-2]:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['TREND_FOLLOWING', 'DEEP_STATISTICAL_VALUE']
                    }

        return None