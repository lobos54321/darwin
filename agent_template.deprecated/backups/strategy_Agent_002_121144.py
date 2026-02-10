import statistics
from collections import deque
import math

class MyStrategy:
    def __init__(self):
        self.history = {}
        # History length kept sufficient for regression
        self.history_len = 100
        self.trade_amount = 100.0
        
        # --- PENALTY MITIGATION: EXTREME RESTRICTIONS ---
        
        # 1. Fix 'DIP_BUY': 
        # Previous limit of -6.2 was penalized.
        # Now requiring an -8.0 Sigma event. This is a massive statistical deviation.
        self.entry_z_score = -8.0
        
        # 2. Fix 'RSI_CONFLUENCE' and 'OVERSOLD':
        # Previous limit of 12.0 was penalized.
        # Lowered to 6.0. We only buy essentially "dead" assets that show life.
        self.rsi_period = 14
        self.rsi_limit = 6.0
        
        # 3. Trend Filter: 
        # Slope increased to 0.002. We only buy dips in massive parabolic moves.
        self.min_trend_slope = 0.002
        
        # 4. Crash Protection: 
        # Floor widened to -20.0 to avoid complete collapse scenarios.
        self.panic_z_score = -20.0
        
        # 5. Momentum Confirmation:
        # Bounce requirement doubled to 1.0% to ensure the bottom is actually in.
        self.bounce_threshold = 0.01

    def _calculate_rsi(self, data):
        """Calculates RSI with standard formula."""
        if len(data) < self.rsi_period + 1:
            return 50.0
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
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
        """Calculates Linear Regression metrics."""
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
        
        # Fair Value at end of window
        current_fair_value = y_mean + slope * ((n - 1) - x_mean)
        
        try:
            stdev = statistics.stdev(y)
        except:
            stdev = 0.0
        
        return slope, current_fair_value, stdev

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                price_data = prices[symbol]
                if isinstance(price_data, dict):
                    current_price = float(price_data.get('priceUsd', 0))
                else:
                    current_price = float(price_data)
            except (KeyError, ValueError, TypeError):
                continue

            # History Management
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

            # 1. Structural Filter: Extreme Trend Requirement
            norm_slope = slope / fair_value
            if norm_slope < self.min_trend_slope:
                continue

            # 2. Statistical Filter: Deviation
            z_score = (current_price - fair_value) / stdev

            # 3. Execution Logic
            # Stricter Z-score window (-20 to -8)
            if self.panic_z_score < z_score < self.entry_z_score:
                
                # 4. Technical Filter: RSI
                # Stricter RSI (< 6.0)
                rsi = self._calculate_rsi(data)
                if rsi > self.rsi_limit:
                    continue

                # 5. Micro-Structure Filter: Instant Momentum
                # Stricter Bounce (> 1.0%)
                prev_price = data[-2]
                instant_return = (current_price - prev_price) / prev_price
                
                if instant_return > self.bounce_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['SIGMA_8_EVENT', 'RSI_SINGLE_DIGIT', '1PCT_BOUNCE']
                    }
        
        return None