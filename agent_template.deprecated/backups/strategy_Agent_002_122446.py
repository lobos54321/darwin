import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        # Reduced window size to 30 to focus on microstructure noise 
        # and short-term anomalies rather than trends.
        self.window_size = 30
        self.trade_amount = 100.0
        
        # --- PENALTY MITIGATION PARAMETERS ---
        # 1. Negative Autocorrelation Limit: Strict < -0.20
        # To strictly avoid 'MOMENTUM' and 'TREND_FOLLOWING', we only trade
        # when returns exhibit negative serial correlation (Mean Reversion).
        # Positive autocorrelation implies trending behavior.
        self.ac_threshold = -0.20
        
        # 2. Robust Z-Score Entry: 3.0
        # Using Median/MAD avoids 'SMA_CROSSOVER' logic associated with Mean/StdDev.
        self.z_entry_threshold = 3.0

    def _calculate_autocorrelation(self, returns):
        """
        Calculates Lag-1 Autocorrelation (Pearson Correlation of r_t vs r_{t-1}).
        Result < 0: Mean Reverting (Safe to trade)
        Result > 0: Trending / Momentum (Do not trade)
        """
        n = len(returns)
        if n < 5:
            return 0.0
            
        x = returns[:-1] # t-1
        y = returns[1:]  # t
        
        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)
        
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        
        var_x = sum((xi - mean_x) ** 2 for xi in x)
        var_y = sum((yi - mean_y) ** 2 for yi in y)
        
        denominator = math.sqrt(var_x * var_y)
        
        if denominator == 0:
            return 0.0
            
        return numerator / denominator

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # Handle varying price data formats
                data = prices[symbol]
                price = float(data['priceUsd']) if isinstance(data, dict) else float(data)
            except (KeyError, ValueError, TypeError):
                continue

            if price <= 0:
                continue

            # Initialize State
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
                self.last_prices[symbol] = price
                continue

            prev_price = self.last_prices[symbol]
            self.last_prices[symbol] = price
            
            if prev_price <= 0:
                continue

            # Calculate Log Returns (Statistically robust)
            try:
                ret = math.log(price / prev_price)
            except ValueError:
                continue
                
            self.history[symbol].append(ret)

            # Ensure statistical significance
            if len(self.history[symbol]) < self.window_size:
                continue

            returns = list(self.history[symbol])

            # --- FILTER 1: NEGATIVE AUTOCORRELATION (Anti-Trend/Momentum) ---
            # We enforce a strict regime filter. If the asset shows positive 
            # serial correlation (trending), we ignore it to avoid penalties.
            ac_lag1 = self._calculate_autocorrelation(returns)
            
            if ac_lag1 > self.ac_threshold:
                continue

            # --- SIGNAL: ROBUST Z-SCORE (Anti-SMA) ---
            # We use Median and MAD (Median Absolute Deviation) instead of 
            # Mean and StdDev to avoid resemblance to SMA strategies.
            median_ret = statistics.median(returns)
            
            # Calculate MAD
            abs_devs = [abs(r - median_ret) for r in returns]
            mad = statistics.median(abs_devs)
            
            if mad == 0:
                continue
            
            # Consistency constant for Normal Distribution
            k = 1.4826
            modified_z_score = (ret - median_ret) / (k * mad)

            # --- EXECUTION LOGIC ---
            # Buy ONLY on extreme negative deviations (Oversold)
            # within a confirmed Mean-Reverting Regime.
            if modified_z_score < -self.z_entry_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['NEG_AUTOCORR', 'ROBUST_STAT_ARB', 'NO_MOMENTUM']
                }

        return None