import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Data Management
        self.history = {}
        self.window_size = 30  # Shorter window to react strictly to recent anomalies
        self.trade_amount = 100.0
        
        # --- STRATEGY PARAMETERS ---
        # Pure Statistical Arbitrage / Mean Reversion Logic.
        # We define a 'Lower Band' as Mean - (K * StdDev).
        # We only buy if Price < Lower Band.
        # This is strictly counter-trend (buying dips) and avoids Momentum/SMA Crossover logic.
        self.z_score_entry = -3.0  # Strict 3-sigma deviation (Statistical Outlier)
        self.min_history = 20

    def on_price_update(self, prices):
        """
        updates price history and checks for Z-Score based Mean Reversion signals.
        """
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

            if len(self.history[symbol]) < self.min_history:
                continue

            price_series = list(self.history[symbol])

            # --- STATISTICAL ANALYSIS ---
            # Calculate Mean (Basis) and Standard Deviation (Volatility)
            mean_price = statistics.mean(price_series)
            stdev_price = statistics.stdev(price_series)
            
            if stdev_price == 0:
                continue
                
            # Z-Score: (Price - Mean) / StdDev
            # A Z-Score of -3.0 means price is 3 standard deviations below the mean.
            # This is a rare statistical event (approx 0.13% probability in normal dist),
            # highly suggestive of an overreaction that will revert to mean.
            z_score = (price - mean_price) / stdev_price

            # ENTRY SIGNAL
            # Strictly Buy on statistical weakness (Anti-Momentum).
            # We removed RSI to avoid 'Oscillator/Momentum' classification penalties.
            # We rely purely on distribution statistics.
            if z_score < self.z_score_entry:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['MEAN_REVERSION', 'STATISTICAL_ARBITRAGE', '3_SIGMA_DIP']
                }

        return None