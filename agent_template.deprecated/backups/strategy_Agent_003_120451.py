import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        REFACTORED to eliminate 'DIP_BUY' and 'OVERSOLD' characteristics.
        
        New Logic: MOMENTUM BREAKOUT (H-VBO)
        Instead of Mean Reversion (buying weakness/dips), this strategy captures 
        High-Velocity Breakouts (buying strength).
        
        1. Inverts Z-Score Logic: Triggers on Z > +3.0 (Breakout) instead of Z < -5.0 (Dip).
        2. Trend Following: Only buys when Price > SMA (Momentum) vs Price < SMA (Reversion).
        3. Eliminates RSI: Uses pure statistical variance to define 'Expansion'.
        """
        self.prices_history = {}
        self.window_size = 40  # Rolling window for volatility calculation
        self.trade_amount = 0.1
        self.breakout_threshold = 3.0  # Buy when price is 3 Sigma ABOVE the mean

    def on_price_update(self, prices):
        """
        Analyzes price stream for positive volatility breakouts.
        """
        for symbol in prices:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue

            # Manage History
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
            
            history = self.prices_history[symbol]
            history.append(current_price)

            # Need full window for valid statistics
            if len(history) < self.window_size:
                continue

            data = list(history)
            
            # --- Statistical Calculations ---
            mean_price = statistics.mean(data)
            try:
                stdev_price = statistics.stdev(data)
            except statistics.StatisticsError:
                continue # Variance requires at least two data points

            if stdev_price == 0:
                continue

            # --- Signal Logic: Positive Volatility Breakout ---
            
            # 1. Z-Score Calculation
            # We look for Positive Deviation (Price > Mean)
            deviation = current_price - mean_price
            z_score = deviation / stdev_price

            # 2. Breakout Trigger
            # Fixes 'DIP_BUY': We buy only when price is SURGING away from the mean upwards.
            # Fixes 'OVERSOLD': We are buying in 'Overbought' territory (Trend Following).
            is_breakout = z_score > self.breakout_threshold

            # 3. Momentum Velocity
            # Ensure price is actively ticking up (not a stagnant high).
            prev_price = data[-2]
            velocity_positive = current_price > prev_price

            if is_breakout and velocity_positive:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['MOMENTUM_BREAKOUT', 'POSITIVE_SIGMA', 'TREND_FOLLOWING']
                }

        return None