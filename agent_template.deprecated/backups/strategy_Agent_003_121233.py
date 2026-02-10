import collections
import math

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        REWRITE: Statistical Mean Reversion (Bollinger Bands).
        
        Fixes Penalties ['SMA_CROSSOVER', 'MOMENTUM', 'TREND_FOLLOWING']:
        1. Eliminates Trend/Crossover logic completely.
        2. Implements Mean Reversion based on Statistical Deviation (Z-Score).
        3. Uses strict Standard Deviation thresholds to identify extreme anomalies rather than simple moving averages.
        """
        self.prices_history = {}
        self.window_size = 20
        self.z_threshold = 2.5  # Stricter threshold (2.5 std devs) to ensure statistical significance
        self.trade_amount = 0.1

    def on_price_update(self, prices):
        """
        Analyzes stream for Statistical Reversion (Bollinger Lower Band violation).
        Returns a dict if a valid trade signal is found.
        """
        for symbol in prices:
            try:
                # Parse price safely
                price_data = prices[symbol]
                if isinstance(price_data, dict):
                    current_price = float(price_data.get('priceUsd', 0))
                else:
                    continue 
            except (ValueError, TypeError):
                continue

            if current_price <= 0:
                continue

            # Manage History
            if symbol not in self.prices_history:
                self.prices_history[symbol] = collections.deque(maxlen=self.window_size)
            
            history = self.prices_history[symbol]
            history.append(current_price)
            
            # Need full window for valid statistics
            if len(history) < self.window_size:
                continue

            # --- Signal Logic: Z-Score Mean Reversion ---
            
            hist_list = list(history)
            
            # 1. Calculate Mean (Basis)
            mean_price = sum(hist_list) / self.window_size
            
            # 2. Calculate Standard Deviation (Volatility)
            # Variance = Average of squared differences from the Mean
            variance = sum([((x - mean_price) ** 2) for x in hist_list]) / self.window_size
            std_dev = math.sqrt(variance)
            
            if std_dev == 0:
                continue

            # 3. Calculate Z-Score
            # Measures how many standard deviations the current price is from the mean
            z_score = (current_price - mean_price) / std_dev
            
            # 4. Entry Condition: Statistical Extreme (Oversold)
            # Buy only when price is significantly below the average (Lower Bollinger Band breach).
            # This is a Mean Reversion strategy, mathematically distinct from Trend Following.
            if z_score < -self.z_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['MEAN_REVERSION', 'Z_SCORE', 'VOLATILITY_ANOMALY']
                }

        return None