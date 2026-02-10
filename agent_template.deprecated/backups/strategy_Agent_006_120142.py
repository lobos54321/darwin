import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY REWRITE: Statistical Momentum Breakout
        # Penalties Addressed:
        # 1. 'DIP_BUY': Logic INVERTED. We now buy strength (Positive Z-Score) to capture momentum breakouts, 
        #    eliminating the risk of catching falling knives.
        # 2. 'OVERSOLD': Removed. Strategy focuses on volatility expansion rather than over-extension metrics.
        # 3. 'RSI_CONFLUENCE': Removed. Pure statistical variance approach used.
        
        self.history = {}
        self.window_size = 60  # Rolling window for statistical baseline
        self.trade_amount = 100.0
        
        # Entry Parameters
        # We target price anomalies on the UPSIDE (Breakouts).
        # A Z-Score of +3.0 implies the price is 3 standard deviations above the mean.
        # This targets momentum continuation rather than mean reversion.
        self.z_score_threshold = 3.0 
        self.min_history = 50 

    def on_price_update(self, prices):
        """
        Scans for assets breaking out significantly above their statistical mean (Momentum).
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)  # Randomize execution order to prevent bias

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

            # 4. Calculate Statistics (Mean & Stdev)
            data_window = list(self.history[symbol])
            try:
                mean_price = statistics.mean(data_window)
                stdev_price = statistics.stdev(data_window)
            except statistics.StatisticsError:
                continue

            # Avoid division by zero
            if stdev_price == 0:
                continue

            # 5. Calculate Z-Score (Statistical Deviation)
            z_score = (current_price - mean_price) / stdev_price

            # 6. Signal Logic: MOMENTUM BREAKOUT
            # To fix 'DIP_BUY' and 'OVERSOLD', we invert the logic to look for Strength.
            # We buy if price surges significantly above the mean (Positive Z-Score).
            if z_score > self.z_score_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['MOMENTUM_BREAKOUT', 'VOLATILITY_SURGE']
                }

        return None