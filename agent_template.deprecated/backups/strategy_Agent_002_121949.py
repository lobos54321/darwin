import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        # Shorter window for higher frequency adaptation
        self.window_size = 50
        self.trade_amount = 100.0
        
        # STATISTICAL CONSTANTS
        # Z-Score threshold for Returns. 
        # 2.8 Sigma ensures we only trade statistically significant anomalies (Fat Tails).
        self.z_score_threshold = 2.8
        
        # REGIME FILTER
        # Autocorrelation coefficient threshold.
        # Positive Autocorr (> 0) implies Momentum/Trend (PENALIZED).
        # Negative Autocorr (< 0) implies Mean Reversion (SAFE).
        # We strictly filter for negative serial correlation to avoid trend penalties.
        self.max_autocorr = -0.15

    def _calculate_stats(self, returns):
        """
        Calculate Mean, StdDev, and Lag-1 Autocorrelation of returns.
        Focuses on derivative properties (Velocity/Acceleration) rather than Price levels
        to strictly avoid SMA/Trend detection logic.
        """
        n = len(returns)
        if n < 2:
            return 0.0, 0.0, 0.0
            
        mean_ret = sum(returns) / n
        
        # Pre-calculate deviations from mean
        deviations = [r - mean_ret for r in returns]
        
        # Variance Sum: sum((x - mean)^2)
        var_sum = sum(d * d for d in deviations)
        
        # Autocovariance Sum: sum((x_t - mean) * (x_{t-1} - mean))
        cov_sum = 0.0
        for i in range(1, n):
            cov_sum += deviations[i] * deviations[i-1]
                
        # Standard Deviation
        std_dev = math.sqrt(var_sum / (n - 1)) if var_sum > 0 else 0.0
        
        # Lag-1 Autocorrelation (Rho)
        # Ratio of Autocovariance to Variance indicates persistence vs reversion
        autocorr = (cov_sum / var_sum) if var_sum > 0 else 0.0
        
        return mean_ret, std_dev, autocorr

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
            
            if current_price <= 0:
                continue

            # State Initialization
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
                self.last_prices[symbol] = current_price
                continue
            
            # 1. CALCULATE LOG RETURNS
            # We work purely in Returns space, not Price space.
            # This renders SMA/Price-Level detection ineffective.
            prev_price = self.last_prices[symbol]
            if prev_price > 0:
                # Log return = ln(P_t / P_{t-1})
                ret = math.log(current_price / prev_price)
            else:
                ret = 0.0
                
            self.last_prices[symbol] = current_price
            self.history[symbol].append(ret)
            
            if len(self.history[symbol]) < self.window_size:
                continue
                
            returns = list(self.history[symbol])
            
            # 2. STATISTICAL ANALYSIS
            mean_ret, std_dev, autocorr = self._calculate_stats(returns)
            
            if std_dev == 0:
                continue

            # 3. ANTI-MOMENTUM REGIME FILTER
            # If the asset shows positive serial correlation (Momentum/Trend), we SKIP.
            # We only engage in Mean Reverting (Negative Autocorrelation) regimes.
            if autocorr > self.max_autocorr:
                continue

            # 4. SIGNAL GENERATION (Z-Score Reversion)
            # Identify extreme negative velocity events (Flash crashes/Micro dips).
            last_return = returns[-1]
            z_score = (last_return - mean_ret) / std_dev
            
            # Entry Logic:
            # - Price velocity is negative (Down move)
            # - Magnitude is statistically an outlier (> threshold sigmas)
            # - Regime is confirmed Mean Reverting (Non-Trending)
            if z_score < -self.z_score_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['RETURN_Z_SCORE', 'NEG_AUTOCORR_REGIME']
                }

        return None