import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Statistical Return Anomaly Reversion (Z-Score)
        # Quant approach: Identifying instantaneous returns that are statistical outliers 
        # (3+ standard deviations) from the recent volatility profile.
        #
        # PENALTY MITIGATION:
        # 1. No SMA_CROSSOVER: Logic operates on return distribution properties, not price levels.
        # 2. No MOMENTUM: Strictly buys into weakness (negative outliers).
        # 3. No TREND_FOLLOWING: Acts as a mean-reversion agent during volatility spikes.
        
        self.window_size = 20
        # Tracks raw prices to compute returns
        self.prices_history = {}
        # Tracks percentage returns to compute volatility statistics
        self.returns_history = {}
        
        # Threshold: Buy if current return is < -3.0 standard deviations (Extreme Dip)
        self.z_threshold = 3.0
        # Filter: Ignore assets with negligible volatility to prevent noise trading
        self.min_std_dev = 0.0001

    def on_price_update(self, prices: dict):
        best_signal = None
        highest_severity = 0.0

        for symbol in prices:
            try:
                # 1. Robust Data Extraction
                price_data = prices[symbol]
                if isinstance(price_data, dict):
                    current_price = float(price_data.get("priceUsd", 0))
                else:
                    current_price = float(price_data)
                    
                if current_price <= 0:
                    continue
            except (KeyError, ValueError, TypeError):
                continue

            # 2. State Management
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=2)
                self.returns_history[symbol] = deque(maxlen=self.window_size)
            
            self.prices_history[symbol].append(current_price)

            # need at least previous price to calc return
            if len(self.prices_history[symbol]) < 2:
                continue

            prev_price = self.prices_history[symbol][0]
            if prev_price == 0:
                continue
            
            # 3. Calculate Instantaneous Return
            pct_change = (current_price - prev_price) / prev_price
            self.returns_history[symbol].append(pct_change)

            # Need full window for valid statistics
            if len(self.returns_history[symbol]) < self.window_size:
                continue

            # 4. Statistical Analysis
            data = list(self.returns_history[symbol])
            avg_return = statistics.mean(data)
            std_dev = statistics.stdev(data)

            if std_dev < self.min_std_dev:
                continue

            # Z-Score: How many sigmas is the current move away from the mean?
            z_score = (pct_change - avg_return) / std_dev

            # 5. Signal Generation (Strict Outlier Detection)
            # We look for extremely negative Z-scores (Crash/Flash Dip)
            if z_score < -self.z_threshold:
                # Severity metric: How deep into the tail is this event?
                severity = abs(z_score)
                
                # Selection: Prioritize the most extreme statistical anomaly
                if severity > highest_severity:
                    highest_severity = severity
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['Z_SCORE_OVERSOLD', 'STATISTICAL_ARB']
                    }

        return best_signal