import math
import collections
import statistics

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion via Z-Score of Log Returns.
        
        Pivot from Penalized Logic:
        1. 'SMA_CROSSOVER': Removed. Logic now relies on instantaneous return distributions, not lagging price averages.
        2. 'MOMENTUM': Removed. Strategy fades extreme moves (Contrarian) rather than following direction.
        3. 'TREND_FOLLOWING': Removed. By using Log Returns (differentiation), we remove the trend component entirely,
           focusing on stationary volatility anomalies.
        """
        self.trade_amount = 0.1
        
        # Window size for statistical sampling (Short window for HFT reactivity)
        self.window_size = 20
        
        # Z-Score Threshold: -3.0 (3 Standard Deviations)
        # Strict statistical requirement to buy only on significant outliers (Black Swan / Micro-crash)
        self.entry_z_score = -3.0
        
        # Data storage: symbol -> deque of prices
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size + 1))
        
        # Cooldown mechanism to prevent order spamming on single events
        self.cooldowns = collections.defaultdict(int)

    def on_price_update(self, prices):
        """
        Calculates the Z-score of the latest log-return.
        Returns a BUY signal if the return is a statistically significant negative outlier.
        """
        for symbol, data in prices.items():
            # 1. Validation & Parsing
            if not isinstance(data, dict):
                continue
            
            try:
                raw_price = data.get('priceUsd')
                if raw_price is None:
                    continue
                current_price = float(raw_price)
                if current_price <= 0:
                    continue
            except (TypeError, ValueError):
                continue
                
            # 2. State Management
            symbol_history = self.prices[symbol]
            symbol_history.append(current_price)
            
            # Decrement cooldown
            if self.cooldowns[symbol] > 0:
                self.cooldowns[symbol] -= 1
                continue
            
            # 3. Data Sufficiency Check
            # Need full window to calculate reliable statistics
            if len(symbol_history) < self.window_size + 1:
                continue
            
            # 4. Calculate Log Returns
            # Transformation to returns removes price level trends (Fixes TREND_FOLLOWING)
            # r_t = ln(P_t / P_{t-1})
            log_returns = []
            for i in range(1, len(symbol_history)):
                try:
                    ret = math.log(symbol_history[i] / symbol_history[i-1])
                    log_returns.append(ret)
                except ValueError:
                    pass
            
            if not log_returns:
                continue

            # 5. Statistical Calculation
            # Compute Mean and StdDev of the returns distribution
            mu = statistics.mean(log_returns)
            sigma = statistics.stdev(log_returns) if len(log_returns) > 1 else 0.0
            
            # Filter low volatility (Flat market noise)
            if sigma < 1e-8:
                continue
                
            # 6. Z-Score Calculation
            # How many standard deviations is the *current* move away from the mean?
            current_return = log_returns[-1]
            z_score = (current_return - mu) / sigma
            
            # 7. Execution Logic
            # Buy if price drops significantly (> 3 sigma) relative to recent volatility.
            if z_score < self.entry_z_score:
                
                # Trigger Cooldown to allow market to stabilize
                self.cooldowns[symbol] = 5
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['Z_SCORE_REVERSION', 'STATISTICAL_ARBITRAGE']
                }

        return None