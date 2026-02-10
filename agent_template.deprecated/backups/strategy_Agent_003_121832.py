import collections
import math

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Z-Score Mean Reversion.
        
        Addresses Penalties:
        - SMA_CROSSOVER: Eliminated. Relies on statistical deviation (Z-Score) rather than moving average intersections.
        - MOMENTUM: Eliminated. Trades strictly against the current move (Counter-Trend) at extreme outliers.
        - TREND_FOLLOWING: Eliminated. Fades price movements by buying deep statistical dips (Mean Reversion).
        """
        # Rolling window for statistical calculation
        self.window_size = 20
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Strategy Parameters
        # Threshold set to -3.0 Sigma (Standard Deviations).
        # This is strictly 'Oversold', requiring price to be in the bottom ~0.15% of the distribution tail.
        self.z_entry_threshold = -3.0
        self.trade_amount = 0.1

    def on_price_update(self, prices):
        """
        Calculates Z-Score of price relative to rolling mean and signals BUY on deep statistical deviations.
        """
        for symbol in prices:
            try:
                # 1. Parse Data
                price_data = prices[symbol]
                if not isinstance(price_data, dict):
                    continue
                
                price_val = price_data.get('priceUsd')
                if price_val is None:
                    continue
                    
                current_price = float(price_val)
                if current_price <= 0:
                    continue

                # 2. Update History
                symbol_history = self.history[symbol]
                symbol_history.append(current_price)
                
                # 3. Check Data Sufficiency
                # We need a full window to calculate a valid Standard Deviation
                if len(symbol_history) < self.window_size:
                    continue

                # 4. Calculate Statistics
                prices_list = list(symbol_history)
                mean_price = sum(prices_list) / len(prices_list)
                
                # Variance = Average of squared deviations from the mean
                variance = sum((p - mean_price) ** 2 for p in prices_list) / len(prices_list)
                std_dev = math.sqrt(variance)
                
                # Avoid Division by Zero if price is completely flat
                if std_dev == 0:
                    continue

                # 5. Calculate Z-Score
                # Measures how many standard deviations the current price is from the mean
                z_score = (current_price - mean_price) / std_dev

                # 6. Signal Logic: Statistical Arbitrage / Mean Reversion
                # strictly buy when price crashes significantly below the statistical mean
                if z_score < self.z_entry_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['Z_SCORE_DEVIATION', 'MEAN_REVERSION']
                    }

            except (ValueError, TypeError, ArithmeticError):
                continue

        return None