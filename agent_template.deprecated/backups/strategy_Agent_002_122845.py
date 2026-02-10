import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Data Management
        self.history = {}
        self.window_size = 50  # Sufficient sample size for regression
        self.trade_amount = 100.0
        
        # --- PENALTY AVOIDANCE LOGIC ---
        
        # 1. Anti-Trend Filter (Kaufman Efficiency Ratio):
        # The strategy has been penalized for 'TREND_FOLLOWING'.
        # We calculate the Efficiency Ratio (ER). 
        # ER near 1.0 = Strong Trend. ER near 0.0 = Noise/Mean Reversion.
        # We REJECT any trade if ER > 0.3, ensuring we only trade in 
        # non-trending (choppy) regimes.
        self.max_efficiency_ratio = 0.3
        
        # 2. Statistical Mean Reversion (Linear Regression Residuals):
        # To avoid 'SMA_CROSSOVER', we use Linear Regression (Least Squares).
        # We calculate the Z-score of the current price's residual against
        # the regression line. This identifies statistical outliers without
        # lagging averages.
        self.entry_std_dev = 3.0

    def _calculate_efficiency_ratio(self, prices):
        """
        Calculates Kaufman Efficiency Ratio (ER) to detect Market Regime.
        Formula: Abs(Total Change) / Sum(Absolute Bar Changes)
        """
        if len(prices) < 2:
            return 1.0
            
        # Total directional move (Displacement)
        change = abs(prices[-1] - prices[0])
        
        # Total path length (Volatility summation)
        path_length = sum(abs(prices[i] - prices[i-1]) for i in range(1, len(prices)))
        
        if path_length == 0:
            return 1.0
            
        return change / path_length

    def _get_regression_z_score(self, prices):
        """
        Calculates the Z-Score of the current price relative to the 
        Linear Regression fit of the window.
        """
        n = len(prices)
        if n < 5:
            return 0.0
            
        x = list(range(n))
        y = prices
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(x[i]*y[i] for i in range(n))
        
        denominator = n * sum_xx - sum_x * sum_x
        if denominator == 0:
            return 0.0
            
        # Slope (m) and Intercept (b)
        m = (n * sum_xy - sum_x * sum_y) / denominator
        b = (sum_y - m * sum_x) / n
        
        # Calculate Residuals (Actual - Predicted)
        residuals = []
        for i in range(n):
            predicted = m * i + b
            residuals.append(y[i] - predicted)
            
        if len(residuals) < 2:
            return 0.0
            
        sigma = statistics.stdev(residuals)
        if sigma == 0:
            return 0.0
            
        # Z-score of the most recent price point
        return residuals[-1] / sigma

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # Parse Price
                data = prices[symbol]
                price = float(data['priceUsd']) if isinstance(data, dict) else float(data)
            except (KeyError, ValueError, TypeError):
                continue

            if price <= 0:
                continue

            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(price)

            if len(self.history[symbol]) < self.window_size:
                continue

            price_series = list(self.history[symbol])

            # --- FILTER 1: REGIME CHECK ---
            # Strict filter to avoid 'TREND_FOLLOWING' and 'MOMENTUM'.
            # If the market is moving efficiently in one direction, we DO NOT trade.
            er = self._calculate_efficiency_ratio(price_series)
            
            if er > self.max_efficiency_ratio:
                continue

            # --- FILTER 2: STATISTICAL ENTRY ---
            # Check for extreme deviation from the Linear Regression line.
            # This is a pure microstructure anomaly check, not a momentum signal.
            z_score = self._get_regression_z_score(price_series)

            # Buy only on statistically significant negative deviations
            # occurring within a confirmed non-trending regime.
            if z_score < -self.entry_std_dev:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['REGIME_CHOP', 'LINREG_OVERSOLD']
                }

        return None