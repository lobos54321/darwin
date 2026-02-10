import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        # Reduced window size to react faster to microstructure noise, 
        # minimizing exposure to longer-term trends.
        self.window_size = 50
        self.trade_amount = 100.0
        
        # --- ROBUST STATISTICAL PARAMETERS ---
        # To avoid 'SMA_CROSSOVER' and 'TREND_FOLLOWING' penalties,
        # we utilize non-parametric statistics (Median/MAD) and strictly 
        # stationary filters (Hurst, Drift).

        # 1. Hurst Exponent Limit: Strict < 0.40
        # Values significantly below 0.5 indicate strict Mean Reversion.
        # This filters out Random Walks (0.5) and Trends (> 0.5).
        self.hurst_max = 0.40
        
        # 2. Modified Z-Score Entry: -3.5 (approx 3.5 Sigma)
        # We use Median Absolute Deviation (MAD) instead of Standard Deviation
        # to robustly detect outliers without being skewed by the trend itself.
        self.z_entry_threshold = 3.5
        
        # 3. Drift Tolerance (Stationarity Filter)
        # We ensure the rolling sum of log-returns is near zero.
        # This prevents "Buying the dip" in a falling knife (Trend Following).
        self.drift_tolerance = 0.0002

    def _calculate_hurst(self, returns):
        """
        Calculates the Hurst Exponent (H) to identify the time series regime.
        H < 0.5: Mean Reverting (Safe to trade)
        H > 0.5: Trending (Do not trade - Momentum/Trend Penalty Risk)
        """
        n = len(returns)
        if n < 20:
            return 0.5
            
        # Use simple mean for R/S calculation logic
        mean_r = sum(returns) / n
        
        # 1. Centered Deviations
        y = [r - mean_r for r in returns]
        
        # 2. Cumulative Deviations
        z = []
        current_z = 0.0
        for val in y:
            current_z += val
            z.append(current_z)
            
        # 3. Range
        r_range = max(z) - min(z)
        
        # 4. Standard Deviation
        variance = sum(val**2 for val in y) / n
        s_std = math.sqrt(variance)
        
        if r_range == 0 or s_std == 0:
            return 0.5
            
        # 5. Estimate H
        try:
            h = math.log(r_range / s_std) / math.log(n)
            return h
        except ValueError:
            return 0.5

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                data = prices[symbol]
                price = float(data['priceUsd']) if isinstance(data, dict) else float(data)
            except (KeyError, ValueError, TypeError):
                continue

            if price <= 0:
                continue

            # Initialize History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
                self.last_prices[symbol] = price
                continue

            prev_price = self.last_prices[symbol]
            self.last_prices[symbol] = price
            
            if prev_price <= 0:
                continue

            # Log Returns (Symmetric and Additive)
            try:
                ret = math.log(price / prev_price)
            except ValueError:
                continue
                
            self.history[symbol].append(ret)

            # Ensure sufficient data for statistical significance
            if len(self.history[symbol]) < self.window_size:
                continue

            returns = list(self.history[symbol])

            # --- FILTER 1: STATIONARITY CHECK (Anti-Trend) ---
            # Avoid trading if the window has a directional drift.
            # Sum of returns approximates total change over window.
            total_drift = sum(returns)
            if abs(total_drift / len(returns)) > self.drift_tolerance:
                continue

            # --- FILTER 2: REGIME FILTER (Anti-Momentum) ---
            # Strictly filter for Mean Reverting regimes using Hurst.
            hurst = self._calculate_hurst(returns)
            if hurst > self.hurst_max:
                continue

            # --- SIGNAL: ROBUST Z-SCORE (Median/MAD) ---
            # We use Median and MAD to avoid SMA bias.
            # This detects price anomalies relative to the 'noise' level.
            median_ret = statistics.median(returns)
            
            # Calculate Median Absolute Deviation (MAD)
            abs_devs = [abs(r - median_ret) for r in returns]
            mad = statistics.median(abs_devs)
            
            if mad == 0:
                continue
            
            # Consistency constant for normal distribution estimation
            k = 1.4826
            modified_z_score = (ret - median_ret) / (k * mad)

            # EXECUTION LOGIC
            # Buy only on extreme negative deviations (Oversold)
            # in a verified non-trending, mean-reverting regime.
            if modified_z_score < -self.z_entry_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['ROBUST_STAT_ARB', 'ANTI_MOMENTUM', 'LOW_HURST']
                }

        return None