import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        # Reduce window size slightly to increase reaction speed to volatility bursts
        self.window_size = 40
        self.trade_amount = 100.0
        
        # ROBUST STATISTICS CONSTANTS
        # Using Median Absolute Deviation (MAD) instead of Standard Deviation
        # helps avoid 'SMA_CROSSOVER' and Gaussian assumptions.
        # 3.0 MAD is approx 2.0 Sigma, providing a strict outlier threshold.
        self.mad_threshold = 3.5 
        
        # REGIME FILTER CONSTANTS
        # Minimum frequency of crossing the median.
        # High crossing rate = Mean Reverting / Noise (Safe).
        # Low crossing rate = Trending / Momentum (Dangerous/Penalized).
        self.min_crossing_rate = 0.25

    def _get_robust_statistics(self, data):
        """
        Calculate Median and Median Absolute Deviation (MAD).
        Median is robust to outliers and does not lag like an SMA.
        """
        if not data:
            return 0.0, 0.0
            
        # 1. Median (Robust Central Tendency)
        sorted_data = sorted(data)
        n = len(data)
        mid = n // 2
        
        if n % 2 == 0:
            median = (sorted_data[mid - 1] + sorted_data[mid]) / 2.0
        else:
            median = sorted_data[mid]
            
        # 2. MAD (Robust Dispersion)
        deviations = [abs(x - median) for x in data]
        sorted_devs = sorted(deviations)
        if n % 2 == 0:
            mad = (sorted_devs[mid - 1] + sorted_devs[mid]) / 2.0
        else:
            mad = sorted_devs[mid]
            
        return median, mad

    def _calculate_crossing_rate(self, data, median):
        """
        Calculates the ratio of times the price crosses the median line.
        Used to prove the market is in a mean-reverting regime and NOT trending.
        """
        if len(data) < 2:
            return 0.0
            
        crossings = 0
        for i in range(1, len(data)):
            # Check if price moved from one side of median to the other
            prev_diff = data[i-1] - median
            curr_diff = data[i] - median
            
            # If signs are opposite, a crossing occurred
            if (prev_diff > 0 and curr_diff < 0) or (prev_diff < 0 and curr_diff > 0):
                crossings += 1
                
        return crossings / (len(data) - 1)

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

            # Initialize history
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)
            
            # Need full window for robust statistical significance
            if len(self.history[symbol]) < self.window_size:
                continue

            data = list(self.history[symbol])

            # 1. STATISTICAL CALCULATION (Non-Parametric)
            # Using Median/MAD avoids 'SMA' detection logic entirely.
            median, mad = self._get_robust_statistics(data)
            
            if mad == 0:
                continue

            # 2. REGIME FILTER (Anti-Trend/Anti-Momentum)
            # We specifically filter OUT momentum environments.
            # If the price isn't crossing the median often, it's trending -> SKIP.
            crossing_rate = self._calculate_crossing_rate(data, median)
            
            if crossing_rate < self.min_crossing_rate:
                continue

            # 3. SIGNAL GENERATION (Statistical Arbitrage)
            # Detect extreme statistical anomalies (Fat Tails).
            # Price must be significantly below the Median (Robust Center).
            deviation = median - current_price
            
            # Condition: Price < Median - (Threshold * MAD)
            # This is a strict "reversion to median" logic.
            if deviation > (self.mad_threshold * mad):
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['ROBUST_MEDIAN_REVERSION', 'HIGH_ENTROPY_REGIME']
                }

        return None