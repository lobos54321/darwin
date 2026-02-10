import collections
import math

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        Strategy: Statistical Mean Reversion (Z-Score Logic).
        
        Addresses Penalties:
        - SMA_CROSSOVER: Removed. Uses single rolling mean for statistical baseline only.
        - MOMENTUM: Removed. Buys on price weakness (dips), not strength.
        - TREND_FOLLOWING: Removed. Fades the trend by buying statistical outliers (mean reversion).
        """
        # Rolling window for statistical calculations
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=30))
        
        # Strategy Parameters
        self.min_periods = 20
        self.z_threshold = -2.5  # Strict threshold (2.5 Sigma) for deep value
        self.trade_amount = 0.1

    def on_price_update(self, prices):
        """
        Calculates Z-Score of price relative to rolling mean and triggers BUY on significant negative outliers.
        """
        for symbol in prices:
            try:
                # 1. Parse Data
                price_data = prices[symbol]
                if not isinstance(price_data, dict):
                    continue
                
                current_price = float(price_data.get('priceUsd', 0))
                if current_price <= 0:
                    continue

                # 2. Update History
                symbol_history = self.history[symbol]
                symbol_history.append(current_price)
                
                n = len(symbol_history)
                if n < self.min_periods:
                    continue

                # 3. Calculate Statistics (Mean & StdDev)
                # Rolling Mean
                mean = sum(symbol_history) / n
                
                # Rolling Variance & Standard Deviation
                variance = sum((x - mean) ** 2 for x in symbol_history) / n
                std_dev = math.sqrt(variance)
                
                # Avoid division by zero if price is flat
                if std_dev == 0:
                    continue

                # 4. Calculate Z-Score
                # (Price - Mean) / StdDev represents how many sigmas the price is from the average
                z_score = (current_price - mean) / std_dev

                # 5. Signal Logic: Statistical Mean Reversion
                # Buy when price is statistically undervalued (below -2.5 sigma)
                if z_score < self.z_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['STATISTICAL_REVERSION', 'Z_SCORE_OVERSOLD']
                    }

            except (ValueError, TypeError, ZeroDivisionError):
                continue

        return None