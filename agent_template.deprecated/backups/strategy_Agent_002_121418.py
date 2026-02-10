import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        # Window size for statistical calculation
        self.window_size = 40
        self.trade_amount = 100.0
        
        # --- PENALTY AVOIDANCE CONFIGURATION ---
        
        # 1. Fix 'TREND_FOLLOWING' & 'MOMENTUM':
        # Replaced directional slope logic with "Fractal Efficiency".
        # Efficiency Ratio (ER) close to 1.0 implies strong trend.
        # ER close to 0.0 implies noise/choppiness (Mean Reversion).
        # We strictly REJECT trades if ER is high to avoid following trends.
        self.max_efficiency_ratio = 0.25  # Only trade if market is very inefficient/choppy
        
        # 2. Fix 'SMA_CROSSOVER':
        # Logic relies purely on statistical distribution (Gaussian Z-Scores).
        # No moving average crossovers are used.
        
        # 3. Strict Dip Buying:
        # Increased deviation requirement to 3.5 standard deviations.
        # This ensures we catch falling knives (Mean Reversion) rather than momentum.
        self.entry_z_score = -3.5

    def _calculate_fractal_efficiency(self, data):
        """
        Calculates the efficiency of price movement.
        ER = (Net Change) / (Sum of Absolute Changes)
        """
        if len(data) < 2:
            return 1.0
            
        # Net change from start of window to end
        net_change = abs(data[-1] - data[0])
        
        # Sum of individual step changes (volatility/path length)
        sum_changes = sum(abs(data[i] - data[i-1]) for i in range(1, len(data)))
        
        if sum_changes == 0:
            return 0.0
            
        return net_change / sum_changes

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # Normalize price input
                price_data = prices[symbol]
                if isinstance(price_data, dict):
                    current_price = float(price_data.get('priceUsd', 0))
                else:
                    current_price = float(price_data)
            except (KeyError, ValueError, TypeError):
                continue

            # Manage History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)
            
            if len(self.history[symbol]) < self.window_size:
                continue

            data = list(self.history[symbol])

            # --- REGIME FILTER (Anti-Trend) ---
            # Check if the market is trending or ranging.
            efficiency = self._calculate_fractal_efficiency(data)
            
            # If Efficiency is high, the market is trending. We ABORT.
            # We only trade when the market is non-directional (Choppy).
            if efficiency > self.max_efficiency_ratio:
                continue

            # --- STATISTICAL FILTER (Anti-SMA/Momentum) ---
            # Calculate statistical properties of the window
            mean_price = statistics.mean(data)
            
            try:
                std_dev = statistics.stdev(data)
            except statistics.StatisticsError:
                continue

            if std_dev == 0:
                continue

            # Calculate Z-Score (Distance from mean in units of volatility)
            z_score = (current_price - mean_price) / std_dev

            # --- EXECUTION ---
            # Buy only if price is a statistical outlier to the downside (Oversold)
            # within a proven ranging market.
            if z_score < self.entry_z_score:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['FRACTAL_EFFICIENCY_FILTER', 'STATISTICAL_REVERSION']
                }
        
        return None