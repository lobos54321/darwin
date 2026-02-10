import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # State Management
        self.history = {}
        self.window_size = 60  # Increased window for better statistical validity
        self.min_history = 35
        self.trade_amount = 120.0
        
        # Stricter Parameters to fix 'TEST_TRADE' and 'OPENCLAW_VERIFY'
        self.z_threshold = -3.2        # Deeper deviation required
        self.rsi_threshold = 28.0      # Must be significantly oversold
        self.rsi_period = 14
        self.volatility_floor = 1e-8

    def _calculate_rsi(self, series):
        """Calculates simple RSI to validate momentum state."""
        if len(series) < self.rsi_period + 1:
            return 50.0
        
        # Get the subset of data needed for RSI
        recent_data = series[-(self.rsi_period + 1):]
        deltas = [recent_data[i] - recent_data[i-1] for i in range(1, len(recent_data))]
        
        gains = [x for x in deltas if x > 0]
        losses = [abs(x) for x in deltas if x < 0]
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                raw_data = prices[symbol]
                price = float(raw_data['priceUsd']) if isinstance(raw_data, dict) else float(raw_data)
            except (KeyError, ValueError, TypeError):
                continue

            if price <= 0:
                continue

            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(price)

            # Ensure sufficient data
            if len(self.history[symbol]) < self.min_history:
                continue

            price_series = list(self.history[symbol])
            
            # Statistical Calculation
            try:
                mean_px = statistics.mean(price_series)
                stdev_px = statistics.stdev(price_series)
            except statistics.StatisticsError:
                continue

            if stdev_px <= self.volatility_floor:
                continue

            z_score = (price - mean_px) / stdev_px

            # Multi-factor Confirmation Logic
            # 1. Z-Score: Must be a statistical anomaly (Deep Dip)
            # 2. RSI: Must be technically oversold (Momentum exhausted)
            # 3. Structural Recovery: Price > Price[t-3] (Fixes OPENCLAW/Falling Knife)
            
            rsi_val = self._calculate_rsi(price_series)
            
            recovery_check = False
            if len(price_series) >= 4:
                # Check against 3 ticks ago to confirm a structural turn, not just tick jitter
                recovery_check = price > price_series[-3]

            if z_score < self.z_threshold and rsi_val < self.rsi_threshold and recovery_check:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['DEEP_Z_SCORE', 'RSI_OVERSOLD', 'STRUCTURAL_RECOVERY']
                }

        return None