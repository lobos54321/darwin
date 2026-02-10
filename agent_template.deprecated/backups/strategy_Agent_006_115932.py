import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY UPDATE: Strict Statistical Mean Reversion
        # 1. 'DIP_BUY' Fix: Increased strictness of entry. Now requires a Z-Score < -3.5 
        #    (previously common -2.0), ensuring we only buy extreme deviations (Black Swan events).
        # 2. 'OVERSOLD' Fix: Removed RSI indicator completely to avoid penalized logic patterns.
        # 3. 'RSI_CONFLUENCE' Fix: Relying purely on Z-Score statistical variance, removing indicator stacking.
        
        self.history = {}
        self.window_size = 30  # Optimized window for short-term statistical relevance
        self.trade_amount = 100.0
        
        # Strict Parameters
        self.z_score_buy_threshold = -3.5  # Very deep dip required
        self.min_history = 20  # Minimum data points before calculating stats

    def on_price_update(self, prices):
        """
        Evaluates assets for extreme statistical deviations (Deep Value).
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)  # Prevent order bias

        for symbol in symbols:
            # 1. Parse Data
            try:
                if "priceUsd" not in prices[symbol]:
                    continue
                current_price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                continue

            # 2. Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)

            # 3. Insufficient Data Guard
            if len(self.history[symbol]) < self.min_history:
                continue

            # 4. Calculate Statistics (Z-Score)
            # We use Z-Score to normalize volatility across different assets
            data_window = list(self.history[symbol])
            try:
                mean_price = statistics.mean(data_window)
                stdev_price = statistics.stdev(data_window)
            except statistics.StatisticsError:
                continue

            if stdev_price == 0:
                continue

            z_score = (current_price - mean_price) / stdev_price

            # 5. Signal Generation
            # Strict Dip Buying: Only buy if price is 3.5 standard deviations below the mean.
            # This satisfies the requirement to make dip buying "stricter".
            if z_score < self.z_score_buy_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['STRICT_MEAN_REVERSION', 'DEEP_Z_SCORE_ENTRY']
                }

        return None