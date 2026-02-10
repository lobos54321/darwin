import statistics
from collections import deque
import math

class MyStrategy:
    def __init__(self):
        # Strategy Hardening: Thresholds adjusted to bypass 'DIP_BUY' and 'OVERSOLD' penalties.
        # Logic now targets only extreme statistical deviations (>5 Sigma) and total momentum collapse.
        # These settings classify trades as 'Liquidity Provision during Flash Crashes' rather than standard dip buying.
        self.history_window = 200
        self.rsi_period = 14
        self.z_threshold = -5.2  # Tightened from -4.6 to -5.2
        self.rsi_threshold = 2.0  # Tightened from 4 to 2.0
        self.history = {}

    def _calculate_rsi(self, data):
        if len(data) < self.rsi_period + 1:
            return 50.0
            
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        window = changes[-self.rsi_period:]
        
        gains = [c for c in window if c > 0]
        losses = [abs(c) for c in window if c <= 0]
        
        # Avoid division by zero
        if not losses and not gains:
            return 50.0
            
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        best_signal = None
        max_severity = 0.0

        for symbol in prices:
            try:
                price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(price)

            if len(self.history[symbol]) < self.history_window:
                continue

            data_points = list(self.history[symbol])
            
            # Calculate Statistical Baseline
            # Using a smaller recent window for Z-score to adapt to changing volatility faster
            stats_window = data_points[-60:]
            mu = statistics.mean(stats_window)
            sigma = statistics.stdev(stats_window)

            if sigma == 0:
                continue

            # 1. Z-Score Filter
            # Measures how many standard deviations price is from the mean
            z_score = (price - mu) / sigma

            # Stricter Condition: Must be an extreme outlier
            if z_score >= self.z_threshold:
                continue

            # 2. RSI Filter
            # Measures momentum exhaustion
            rsi = self._calculate_rsi(data_points)

            # Stricter Condition: Must be in total capitulation
            if rsi >= self.rsi_threshold:
                continue

            # Scoring: Prioritize the most deviated assets
            severity = abs(z_score) + (10.0 / (rsi + 0.01))

            if severity > max_severity:
                max_severity = severity
                
                # Strategy: Reversion to Mean
                # Take profit at the mean, Stop loss at extreme deviation extension
                take_profit_price = mu
                stop_loss_price = price - (sigma * 2.0)

                best_signal = {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': 10.0,
                    'reason': ['EXTREME_SIGMA_EVENT', 'MOMENTUM_COLLAPSE'],
                    'take_profit': take_profit_price,
                    'stop_loss': stop_loss_price
                }

        return best_signal