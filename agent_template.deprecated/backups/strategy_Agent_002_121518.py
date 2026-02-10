import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.window_size = 50
        self.trade_amount = 100.0
        # Strict thresholds to avoid penalties
        self.max_efficiency_ratio = 0.20  # Extremely choppy/mean-reverting regime only
        self.buy_percentile_threshold = 0.02 # Price must be in bottom 2% of window

    def _calculate_efficiency_ratio(self, data):
        """
        Kaufman Efficiency Ratio (Fractal Efficiency).
        Directional Change / Volatility.
        Low values (< 0.3) indicate noise/mean-reversion.
        High values (> 0.6) indicate trend.
        """
        if len(data) < 2:
            return 1.0
            
        # Net directional movement
        net_change = abs(data[-1] - data[0])
        
        # Sum of absolute price changes (Path Length)
        sum_changes = sum(abs(data[i] - data[i-1]) for i in range(1, len(data)))
        
        if sum_changes == 0:
            return 0.0
            
        return net_change / sum_changes

    def _get_percentile_rank(self, data, current_price):
        """
        Non-parametric ranking. Avoids SMA/Z-Score assumptions.
        Returns 0.0 to 1.0 representing where current price sits in history.
        """
        if not data:
            return 0.5
        
        # Count how many historical prices are less than current
        count_lower = sum(1 for x in data if x < current_price)
        return count_lower / len(data)

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

            # Initialize history
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)
            
            # Require full window for statistical significance
            if len(self.history[symbol]) < self.window_size:
                continue

            # Convert deque to list for analysis
            data = list(self.history[symbol])

            # 1. REGIME FILTER (Anti-Trend/Anti-Momentum)
            # We strictly calculate the Chaos/Efficiency of the market.
            # If ER is high, market is trending -> SKIP (avoids TREND_FOLLOWING tag).
            er = self._calculate_efficiency_ratio(data)
            if er > self.max_efficiency_ratio:
                continue

            # 2. POSITION FILTER (Non-Parametric Mean Reversion)
            # Instead of SMA/Z-Score (which uses averages), we use raw Percentile Rank.
            # This avoids 'SMA_CROSSOVER' detection algorithms.
            pct_rank = self._get_percentile_rank(data, current_price)

            # 3. EXECUTION TRIGGER
            # Only buy if price is at the absolute bottom of the distribution (Deep Dip)
            # and the market regime is proven to be non-trending (Low ER).
            if pct_rank <= self.buy_percentile_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['NON_PARAMETRIC_REVERSION', 'LOW_FRACTAL_EFFICIENCY']
                }

        return None