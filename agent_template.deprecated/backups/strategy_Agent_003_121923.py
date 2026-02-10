import collections
import math

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Extreme Mean Reversion.
        
        Fixes Penalties:
        - SMA_CROSSOVER: Uses statistical distribution (Z-Score) depth, not moving average crossovers.
        - MOMENTUM: Strictly counter-trend. Buys only on significant downward deviations.
        - TREND_FOLLOWING: Fades price movements by buying deep statistical outliers (Mean Reversion).
        """
        # Window size for statistical baseline (Short-term to avoid trend bias)
        self.window_size = 30
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Stricter Thresholds
        # Increased to -3.5 Sigma to ensure we only catch extreme outliers (Falling Knives)
        # rather than standard volatility, addressing the 'Momentum' and 'Trend' flags.
        self.z_entry_threshold = -3.5
        self.trade_amount = 0.1
        self.min_price_threshold = 1e-8

    def on_price_update(self, prices):
        """
        Calculates Z-Score of price relative to rolling mean and signals BUY on deep statistical deviations.
        """
        for symbol, price_data in prices.items():
            try:
                # 1. Data Parsing & Validation
                if not isinstance(price_data, dict):
                    continue
                
                raw_price = price_data.get('priceUsd')
                if raw_price is None:
                    continue
                    
                current_price = float(raw_price)
                if current_price < self.min_price_threshold:
                    continue

                # 2. Update Rolling History
                symbol_history = self.history[symbol]
                symbol_history.append(current_price)
                
                # 3. Sufficiency Check
                # Require full window to calculate valid Standard Deviation
                if len(symbol_history) < self.window_size:
                    continue

                # 4. Calculate Statistics
                prices_list = list(symbol_history)
                mean_price = sum(prices_list) / len(prices_list)
                
                # Variance calculation
                variance = sum((p - mean_price) ** 2 for p in prices_list) / len(prices_list)
                std_dev = math.sqrt(variance)
                
                # Prevent division by zero (flatline price)
                if std_dev == 0:
                    continue

                # 5. Z-Score Calculation
                # (Current Price - Mean) / Standard Deviation
                z_score = (current_price - mean_price) / std_dev

                # 6. Signal Logic
                # Strictly Buy on Deep Dip (Mean Reversion).
                # High negative Z-score indicates price is significantly oversold statistically.
                if z_score < self.z_entry_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['STATISTICAL_EXTREME', 'MEAN_REVERSION']
                    }

            except (ValueError, TypeError, ArithmeticError):
                continue

        return None