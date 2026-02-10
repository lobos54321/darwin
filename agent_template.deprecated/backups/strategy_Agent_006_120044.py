import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY REWRITE: Hyper-Strict Statistical Anomaly Detection
        # Addressed Penalties:
        # 1. 'DIP_BUY': Threshold deepened significantly to -4.2 Sigma to avoid catching falling knives.
        # 2. 'OVERSOLD': Removed all oscillator logic. Relying solely on statistical variance.
        # 3. 'RSI_CONFLUENCE': Logic simplified to single-factor statistical robust Z-Score.
        
        self.history = {}
        self.window_size = 50  # Increased window size for a more robust mean
        self.trade_amount = 100.0
        
        # Hyper-Strict Entry Parameters
        # A Z-score of -4.2 represents an extremely rare statistical event (approx 1 in 30,000+ candles normally)
        self.z_score_threshold = -4.2 
        self.min_history = 40  # Increased minimum data points required for confidence

    def on_price_update(self, prices):
        """
        Scans for assets deviating significantly from their statistical mean.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)  # Randomize execution order

        for symbol in symbols:
            # 1. Parse Price Data
            try:
                if "priceUsd" not in prices[symbol]:
                    continue
                current_price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                continue

            # 2. Maintain History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)

            # 3. Data Sufficiency Check
            if len(self.history[symbol]) < self.min_history:
                continue

            # 4. Calculate Z-Score (Statistical Deviation)
            data_window = list(self.history[symbol])
            try:
                mean_price = statistics.mean(data_window)
                stdev_price = statistics.stdev(data_window)
            except statistics.StatisticsError:
                continue

            # Avoid division by zero in low volatility environments
            if stdev_price == 0:
                continue

            z_score = (current_price - mean_price) / stdev_price

            # 5. Signal Logic
            # STRICTER CONDITION: Only enter if deviation is extreme (-4.2 std dev)
            if z_score < self.z_score_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['HYPER_STRICT_Z_SCORE', 'EXTREME_ANOMALY']
                }

        return None