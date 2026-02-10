import collections
import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Statistical Z-Score Mean Reversion
        
        LOGIC:
        - Treats price action as a mean-reverting process.
        - Calculates the Z-Score (Standard Score) of the current price relative to recent history.
        - Buys only when price deviates significantly below the mean (> 2.5 standard deviations).
        
        COMPLIANCE:
        1. NO 'SMA_CROSSOVER': Uses a single statistical baseline (Mean) and Volatility (StdDev), not crossing averages.
        2. NO 'MOMENTUM': Buys falling prices (Anti-Momentum / Mean Reversion).
        3. NO 'TREND_FOLLOWING': Fades the trend by buying extreme dips.
        """
        # Data window size for statistical significance
        self.window_size = 30
        
        # Risk parameters
        self.z_score_buy_threshold = -2.5  # Strict entry: Price must be 2.5 std devs below mean
        self.min_volatility_ratio = 0.0005 # Minimum volatility to ensure range isn't flat
        
        # History storage: symbol -> deque[price]
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # 1. Parse Data
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                current_price = float(prices[symbol]['priceUsd'])
                self.history[symbol].append(current_price)
                
                # 2. Warmup Check
                if len(self.history[symbol]) < self.window_size:
                    continue
                
                # 3. Calculate Statistics (Mean & Standard Deviation)
                # Convert deque to list for calculation
                window_data = list(self.history[symbol])
                mean_price = sum(window_data) / len(window_data)
                
                # Variance calculation
                variance = sum((p - mean_price) ** 2 for p in window_data) / len(window_data)
                std_dev = math.sqrt(variance)
                
                # 4. Volatility Gate
                # Avoid trading if the market is stagnant (std_dev is negligible)
                if std_dev == 0 or (std_dev / mean_price) < self.min_volatility_ratio:
                    continue
                
                # 5. Z-Score Calculation
                # Standardizes the current price deviation
                z_score = (current_price - mean_price) / std_dev
                
                # 6. Execution Logic
                # Buy if price is strictly oversold (statistically significant dip)
                if z_score <= self.z_score_buy_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 0.1,
                        'reason': ['Z_SCORE_REVERSION', 'STAT_ARB']
                    }
                    
            except Exception:
                continue
        
        return None