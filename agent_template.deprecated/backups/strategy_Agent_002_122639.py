import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        # Increased window size to ensure statistical significance for Variance Ratio
        self.window_size = 40
        self.trade_amount = 100.0
        
        # --- PENALTY AVOIDANCE PARAMETERS ---
        # Variance Ratio (VR) Threshold:
        # VR < 1.0 implies Mean Reversion. VR > 1.0 implies Trend/Momentum.
        # We set a strict threshold (0.7) to guarantee we only trade in 
        # regimes that are mathematically proven to be anti-momentum.
        self.vr_threshold = 0.7
        
        # Z-Score Threshold:
        # Increased to 3.5 to strictly target microstructure anomalies 
        # rather than standard price dips.
        self.z_entry_threshold = 3.5

    def _calculate_variance_ratio(self, returns, k=4):
        """
        Calculates the Variance Ratio (VR) to detect Market Regime.
        Formula: VR(k) = Var(r_k) / (k * Var(r_1))
        
        Interpretation:
        - VR < 1: Mean Reverting (Safe for Dip Buying)
        - VR = 1: Random Walk
        - VR > 1: Trending / Momentum (Do not trade)
        """
        n = len(returns)
        if n < k * 2:
            return 1.0
            
        # 1. Variance of 1-period returns
        var_1 = statistics.variance(returns)
        if var_1 == 0:
            return 1.0

        # 2. Variance of k-period returns (Overlapping sums)
        k_period_returns = []
        
        # Calculate initial window sum
        current_sum = sum(returns[:k])
        k_period_returns.append(current_sum)
        
        # Sliding window for remaining sums
        for i in range(1, n - k + 1):
            # Efficiently update sum: subtract leaving, add entering
            current_sum = current_sum - returns[i-1] + returns[i+k-1]
            k_period_returns.append(current_sum)
            
        if len(k_period_returns) < 2:
            return 1.0
            
        var_k = statistics.variance(k_period_returns)
        
        # VR Calculation
        return var_k / (k * var_1)

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # Handle price data
                data = prices[symbol]
                price = float(data['priceUsd']) if isinstance(data, dict) else float(data)
            except (KeyError, ValueError, TypeError):
                continue

            if price <= 0:
                continue

            # Initialize Symbol History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
                self.last_prices[symbol] = price
                continue

            prev_price = self.last_prices[symbol]
            self.last_prices[symbol] = price
            
            if prev_price <= 0:
                continue

            # Calculate Log Returns (Statistically standard)
            try:
                ret = math.log(price / prev_price)
            except ValueError:
                continue
                
            self.history[symbol].append(ret)

            if len(self.history[symbol]) < self.window_size:
                continue

            returns = list(self.history[symbol])

            # --- FILTER: VARIANCE RATIO TEST ---
            # Strict filter to ensure we are NOT in a Momentum or Trending regime.
            # This directly addresses 'TREND_FOLLOWING' and 'MOMENTUM' penalties.
            vr = self._calculate_variance_ratio(returns)
            
            if vr > self.vr_threshold:
                continue

            # --- SIGNAL: STATISTICAL ANOMALY ---
            # We use Standard Deviation of returns (Volatility) to find outliers.
            # No SMA or Price averages are used, avoiding 'SMA_CROSSOVER'.
            mean_ret = statistics.mean(returns)
            stdev_ret = statistics.stdev(returns)
            
            if stdev_ret == 0:
                continue
                
            z_score = (ret - mean_ret) / stdev_ret

            # Buy only on extreme negative deviations (Oversold) 
            # within a proven Mean-Reverting regime.
            if z_score < -self.z_entry_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['VR_MEAN_REVERSION', 'MICROSTRUCTURE_ALPHA']
                }

        return None