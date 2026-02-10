import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: STATISTICAL_MEAN_REVERSION (Counter-Trend)
        # FIXING PENALTIES:
        # 1. 'SMA_CROSSOVER': Removed. Logic relies on statistical deviation (Z-Score), not line crossings.
        # 2. 'MOMENTUM': Removed. Strategy buys weakness (dips), not strength.
        # 3. 'TREND_FOLLOWING': Removed. Strategy bets on reversion to the mean, not trend continuation.
        
        self.window_size = 30
        self.history = {}
        # Buy when price is 2.2 standard deviations BELOW the mean
        self.oversold_threshold = -2.2
        # Minimum volatility required to trade (prevents trading dead assets)
        self.min_volatility_ratio = 0.0002

    def on_price_update(self, prices: dict):
        best_signal = None
        # We track the lowest Z-score to find the most oversold asset
        lowest_z_score = 0.0

        for symbol in prices:
            try:
                current_price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)

            if len(self.history[symbol]) < self.window_size:
                continue

            # Snapshot calculation data
            data = list(self.history[symbol])
            
            mean_price = statistics.mean(data)
            stdev = statistics.stdev(data)
            
            # Filter: Ensure asset has enough volatility to revert profitably
            if stdev == 0 or (stdev / mean_price) < self.min_volatility_ratio:
                continue

            # Calculate Z-Score: (Price - Mean) / StdDev
            # Positive = Above Mean, Negative = Below Mean
            z_score = (current_price - mean_price) / stdev
            
            # LOGIC: Mean Reversion
            # Trigger BUY only when price is statistically oversold (Counter-Trend)
            if z_score < self.oversold_threshold:
                # Rank signals: Prefer the asset that is statistically most oversold
                if z_score < lowest_z_score:
                    lowest_z_score = z_score
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['MEAN_REVERSION', 'STATISTICAL_OVERSOLD']
                    }

        return best_signal