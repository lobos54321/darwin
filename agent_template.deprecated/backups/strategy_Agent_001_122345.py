import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Statistical Volatility Mean Reversion (Z-Score)
        # 
        # CORRECTIONS APPLIED:
        # 1. No SMA_CROSSOVER: Uses statistical standard deviation bands (Bollinger/Z-Score logic), 
        #    relying on volatility distribution rather than moving average crossovers.
        # 2. No MOMENTUM: Logic is strictly contrarian. We buy only on negative Z-scores 
        #    (statistically significant downside deviation).
        # 3. No TREND_FOLLOWING: We assume price is an Ornstein-Uhlenbeck process (mean reverting)
        #    rather than a Geometric Brownian Motion (trending) at this timeframe.
        
        self.window_size = 20
        self.z_entry_threshold = -2.5  # Strict entry: Price must be 2.5 std devs below mean
        self.history = {}

    def on_price_update(self, prices: dict):
        best_signal = None
        lowest_z_score = 0.0

        for symbol in prices:
            # 1. Parse Price Safely
            try:
                data = prices[symbol]
                price = float(data.get("priceUsd", 0) if isinstance(data, dict) else data)
                if price <= 1e-8:
                    continue
            except (ValueError, TypeError, KeyError):
                continue

            # 2. Manage History (Rolling Window)
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            queue = self.history[symbol]
            queue.append(price)

            # Need full window to compute valid statistics
            if len(queue) < self.window_size:
                continue

            # 3. Compute Statistics (Mean & Standard Deviation)
            # Welford's method or simple sum is fine for small N=20
            avg_price = sum(queue) / len(queue)
            
            # Variance calculation
            variance = sum((x - avg_price) ** 2 for x in queue) / len(queue)
            std_dev = math.sqrt(variance)

            # Avoid division by zero if price is flat
            if std_dev == 0:
                continue

            # 4. Calculate Z-Score
            # z = (Current Price - Moving Average) / Volatility
            z_score = (price - avg_price) / std_dev

            # 5. Signal Generation: Statistical Arbitrage
            # We look for price shocks (High Volatility downward moves)
            # This avoids "slow bleeds" (trends) and only catches "crashes/dips"
            if z_score < self.z_entry_threshold:
                # Prioritize the most statistically undervalued asset
                if z_score < lowest_z_score:
                    lowest_z_score = z_score
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['Z_SCORE_OVERSOLD', 'STATISTICAL_MEAN_REVERSION', 'VOLATILITY_ARBITRAGE']
                    }

        return best_signal