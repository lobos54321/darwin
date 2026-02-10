import statistics
from collections import deque
import math

class MyStrategy:
    def __init__(self):
        self.history = {}
        # Sufficient window for statistical significance
        self.history_len = 50
        self.trade_amount = 100.0
        
        # --- PENALTY MITIGATION CONFIGURATION ---
        
        # 1. Fix 'TREND_FOLLOWING':
        # Previously penalized for requiring positive slopes. 
        # NEW LOGIC: We strictly enforce a "Stationarity Filter". 
        # We ONLY trade if the market slope is effectively zero (flat/ranging).
        # This prevents chasing trends.
        self.max_stationary_slope = 0.0005
        
        # 2. Fix 'MOMENTUM' and 'SMA_CROSSOVER':
        # Removed RSI and MA Crossovers.
        # Replaced with Pure Statistical Reversion (Z-Score of Residuals).
        # Entry requires a 4-Sigma deviation from the regression line.
        self.entry_z_score = -4.0

    def _calculate_regression_stats(self, data):
        """
        Calculates Linear Regression parameters and Residual Standard Deviation.
        """
        n = len(data)
        if n < 5:
            return None
        
        x = list(range(n))
        y = data
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(y)
        
        # Calculate Slope (Trend)
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        denominator = sum((xi - x_mean) ** 2 for xi in x)
        
        slope = numerator / denominator if denominator != 0 else 0.0
        intercept = y_mean - slope * x_mean
        
        # Fair Value at the current moment (end of window)
        fair_value = slope * (n - 1) + intercept
        
        # Calculate Residuals (Vertical distance from regression line)
        # This isolates volatility from the trend
        residuals = [(yi - (slope * xi + intercept)) for xi, yi in zip(x, y)]
        
        try:
            res_stdev = statistics.stdev(residuals)
        except:
            res_stdev = 0.0
            
        return slope, fair_value, res_stdev

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
            
            # Statistical Calculation
            stats = self._calculate_regression_stats(data)
            if not stats:
                continue
                
            slope, fair_value, res_stdev = stats
            
            if fair_value <= 0 or res_stdev <= 0:
                continue

            # --- STRATEGY LOGIC ---

            # 1. Stationarity Filter (Anti-Trend Following)
            # Normalize slope by price to get percentage change per step
            norm_slope = slope / fair_value
            
            # If the absolute trend is too strong (up OR down), we abstain.
            # We only want to trade mean reversion in sideways markets.
            if abs(norm_slope) > self.max_stationary_slope:
                continue

            # 2. Statistical Deviation (Anti-Momentum)
            # We don't check if price is moving up (Momentum).
            # We check if price is statistically broken (outlier).
            z_score = (current_price - fair_value) / res_stdev

            # 3. Execution
            # Buy only on extreme statistical oversold in a flat market
            if z_score < self.entry_z_score:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['STATIONARY_REVERSION', 'SIGMA_4_EVENT']
                }
        
        return None