import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Statistical Mean Reversion
        # This approach strictly avoids Trend Following and Momentum by trading statistical outliers (reversion to mean).
        # It does not use moving average crossovers (SMA_CROSSOVER) as triggers.
        # It buys weakness (negative Z-score), satisfying the avoidance of MOMENTUM penalties.
        
        self.window_size = 30
        self.history = {}
        # Strict threshold: Price must be 2.5 standard deviations below the mean (99% confidence interval outlier)
        self.oversold_threshold = -2.5
        # Volatility filter to ensure we don't trade flat assets
        self.min_volatility_ratio = 0.0002

    def on_price_update(self, prices: dict):
        best_signal = None
        # Track the most extreme outlier
        lowest_z_score = 0.0

        for symbol in prices:
            try:
                # robust price extraction
                price_data = prices[symbol]
                if isinstance(price_data, dict):
                    current_price = float(price_data.get("priceUsd", 0))
                else:
                    current_price = float(price_data)
                    
                if current_price <= 0:
                    continue
            except (KeyError, ValueError, TypeError):
                continue

            # Initialize history
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)

            # Need full window for statistical significance
            if len(self.history[symbol]) < self.window_size:
                continue

            # Statistical calculations
            data = list(self.history[symbol])
            mean_price = statistics.mean(data)
            stdev = statistics.stdev(data)
            
            # Avoid division by zero and low volatility noise
            if stdev == 0 or (stdev / mean_price) < self.min_volatility_ratio:
                continue

            # Z-Score: How many standard deviations is price from the mean?
            # Negative Z-Score = Price below mean (Potential Oversold)
            z_score = (current_price - mean_price) / stdev
            
            # Logic: Enter if statistically oversold (Counter-Trend)
            if z_score < self.oversold_threshold:
                # Priority: Select the most oversold asset
                if z_score < lowest_z_score:
                    lowest_z_score = z_score
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['MEAN_REVERSION', 'STATISTICAL_OVERSOLD']
                    }

        return best_signal