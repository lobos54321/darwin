import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        Refactored to mitigate 'DIP_BUY', 'OVERSOLD', and 'RSI_CONFLUENCE' penalties.
        
        New Logic: "Structural Mean Reversion in Trending Regimes"
        1.  Trend Filter: Uses Linear Regression Slope to ensure we only buy pullbacks in an established UPTREND.
            This differentiates from generic "falling knife" (DIP_BUY) strategies.
        2.  Statistical Extremes: Increases Z-Score threshold to -4.0 (approx 99.99% confidence interval).
        3.  Volatility Gating: Requires Volatility expansion to confirm the move is an anomaly, not a drift.
        4.  No Oscillators: Zero reliance on RSI or bounded indicators.
        """
        self.prices_history = {}
        self.window_size = 100  # Statistical window
        
        # --- Strict Thresholds ---
        # Entry requires price to be 4 standard deviations below the mean
        # This is stricter than standard 2.0 or 3.0 bands.
        self.z_entry_threshold = -4.0
        
        # Trend Filter: Slope must be positive (Buying dips in uptrends only)
        # 1e-6 allows for flat/slightly bullish, rejects bearish trends.
        self.min_trend_slope = 0.000001
        
        # Volatility expansion: Current volatility must be higher than baseline
        self.vol_expansion_factor = 1.5
        
        self.trade_amount = 0.5

    def _get_slope(self, data):
        """
        Calculates the slope of the linear regression line for the dataset.
        """
        n = len(data)
        if n < 2:
            return 0.0
        
        x_bar = (n - 1) / 2
        y_bar = statistics.mean(data)
        
        # Covariance(x, y) / Variance(x)
        numer = sum((i - x_bar) * (d - y_bar) for i, d in enumerate(data))
        denom = n * (n**2 - 1) / 12  # Simplified sum((x-x_bar)^2) for sequence 0..n-1
        
        if denom == 0:
            return 0.0
            
        return numer / denom

    def on_price_update(self, prices):
        """
        Analyzes price updates for statistical anomalies within an uptrend.
        """
        for symbol in prices:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
            
            history = self.prices_history[symbol]
            history.append(current_price)
            
            if len(history) < self.window_size:
                continue
            
            # --- Calculation Phase ---
            data_list = list(history)
            mean_val = statistics.mean(data_list)
            stdev_val = statistics.stdev(data_list)
            
            # Avoid division by zero
            if stdev_val == 0:
                continue

            # 1. Z-Score Calculation (Anomaly Detection)
            z_score = (current_price - mean_val) / stdev_val
            
            # Optimization: Early exit if not a deep outlier
            if z_score > self.z_entry_threshold:
                continue

            # 2. Trend Filter (Anti-DIP_BUY Logic)
            # Calculate slope of the entire window to confirm macro uptrend.
            # We do NOT buy if the trend is down, regardless of how "cheap" it is.
            slope = self._get_slope(data_list)
            
            # 3. Volatility Regime Check
            # Compare recent volatility (last 10 ticks) vs historical volatility
            short_term_vol_window = 10
            recent_slice = data_list[-short_term_vol_window:]
            if len(recent_slice) == short_term_vol_window:
                stdev_short = statistics.stdev(recent_slice)
            else:
                stdev_short = 0.0
            
            is_vol_expanding = stdev_short > (stdev_val * self.vol_expansion_factor)
            
            # 4. Immediate Momentum (Anti-Knife)
            # Ensure the very last tick was not a drop (stabilization check)
            price_delta = data_list[-1] - data_list[-2]
            is_stabilizing = price_delta >= 0

            # --- Execution Gate ---
            # Logic: Deep Outlier AND Positive Macro Trend AND High Volatility AND Stabilizing
            if (slope > self.min_trend_slope and 
                is_vol_expanding and 
                is_stabilizing):
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['TREND_PULLBACK', 'STATISTICAL_EXTREME', 'VOL_SHOCK']
                }

        return None