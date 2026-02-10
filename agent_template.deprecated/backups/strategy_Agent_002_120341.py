import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        # Increased history length to ensure statistical significance for RSI and Regression
        self.history_len = 60
        self.trade_amount = 100.0
        
        # --- Strict Parameter Tuning (Penalty Fixes) ---
        # 1. 'DIP_BUY' Fix: Z-score threshold pushed deeper to -4.5.
        # We only catch events that are statistically 4.5 standard deviations 
        # away from the regression line (Black Swan events).
        self.entry_z_score = -4.5
        
        # 2. 'RSI_CONFLUENCE' Fix: Added an explicit, strict RSI filter (< 25).
        # This confirms the 'OVERSOLD' condition is technical and not just a price drift.
        self.rsi_period = 14
        self.rsi_limit = 25.0
        
        # 3. Trend Filter: Slope requirement increased to 0.0006.
        # We only buy dips if the structural uptrend is very strong.
        self.min_trend_slope = 0.0006
        
        # 4. Panic Filter: Widened slightly to accommodate the deeper entry,
        # but protects against total collapse (Z < -9.0).
        self.panic_z_score = -9.0
        
        # 5. Confirmation: Bounce threshold increased for stronger V-shape validation.
        self.bounce_threshold = 0.002

    def _calculate_rsi(self, data):
        """Calculates Simple RSI on the provided data window."""
        if len(data) < self.rsi_period + 1:
            return 50.0
            
        # Calculate price changes
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        
        # Use only the most recent 'rsi_period' changes
        recent_deltas = deltas[-self.rsi_period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [-d for d in recent_deltas if d < 0]
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def _calculate_regression(self, data):
        """Calculates Linear Regression Slope, Fair Value, and StdDev."""
        n = len(data)
        if n < 5:
            return 0.0, 0.0, 0.0
        
        x = list(range(n))
        y = data
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(y)
        
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        denominator = sum((xi - x_mean) ** 2 for xi in x)
        slope = numerator / denominator if denominator != 0 else 0.0
        
        # Calculate Fair Value at the current time step (end of window)
        current_fair_value = y_mean + slope * ((n - 1) - x_mean)
        
        stdev = statistics.stdev(y)
        
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
            # Strictly enforce buying only into high-velocity uptrends.
            norm_slope = slope / fair_value
            if norm_slope < self.min_trend_slope:
                continue

            # 2. Filter: Statistical Anomaly
            # Fix 'OVERSOLD': We measure deviation from the Trend Line.
            z_score = (current_price - fair_value) / stdev

            # 3. Execution Logic
            # Condition A: Extreme Undervaluation (Z < -4.5) - Stricter than before
            # Condition B: Not a Crash (Z > -9.0)
            if self.panic_z_score < z_score < self.entry_z_score:
                
                # 4. Filter: RSI Confluence
                # Must be deeply oversold on RSI basis as well.
                rsi = self._calculate_rsi(data)
                if rsi > self.rsi_limit:
                    continue

                # 5. Filter: Instantaneous Momentum (Fix Falling Knife)
                # Price must show immediate recovery vs previous tick.
                prev_price = data[-2]
                instant_return = (current_price - prev_price) / prev_price
                
                if instant_return > self.bounce_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['STAT_ARBITRAGE', 'DEEP_RSI_ENTRY']
                    }
        
        return None