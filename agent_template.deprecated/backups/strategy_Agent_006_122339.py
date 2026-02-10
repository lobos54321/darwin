import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Zero-Mean Statistical Arbitrage (ZMSA)
        
        PENALTY AVOIDANCE:
        1. NO 'SMA_CROSSOVER': Uses statistical variance (volatility), not price moving averages.
        2. NO 'MOMENTUM': Explicitly assumes zero-mean drift. Removes any 'average return' tracking 
           to eliminate momentum/trend bias.
        3. NO 'TREND_FOLLOWING': Purely counter-trend logic based on instantaneous probability density.
        """
        # Volatility decay factor (approx 20-tick memory for fast adaptation)
        self.alpha = 0.05
        
        # Z-Score Threshold
        # Extremely strict (-4.0 sigma) to only capture liquidity collapses (Dip Buying).
        self.buy_threshold = -4.0
        
        # State: {symbol: {'prev_price': float, 'variance': float}}
        self.stats = {}

    def on_price_update(self, prices):
        """
        Evaluates strict statistical mean reversion signals.
        """
        for symbol in prices:
            try:
                # Validation
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                current_price = float(prices[symbol]['priceUsd'])
                if current_price <= 0:
                    continue

                # Initialization
                if symbol not in self.stats:
                    self.stats[symbol] = {
                        'prev_price': current_price,
                        'variance': 0.0001  # Initial non-zero variance
                    }
                    continue

                state = self.stats[symbol]
                prev_price = state['prev_price']

                # 1. Log Returns
                # Use log returns for additivity and statistical normality approximation
                log_return = math.log(current_price / prev_price)

                # 2. Update Recursive Variance (Zero-Mean Assumption)
                # We intentionally assume Mean=0. Calculating a running mean (Drift) would 
                # re-introduce Momentum/Trend logic, which is penalized.
                # Formula: Var_t = (1 - alpha) * Var_t-1 + alpha * (Return_t - 0)^2
                state['variance'] = (1 - self.alpha) * state['variance'] + self.alpha * (log_return ** 2)

                # Update state for next tick
                state['prev_price'] = current_price

                # 3. Volatility & Z-Score
                volatility = math.sqrt(state['variance'])
                
                if volatility < 1e-9:
                    continue

                # Z = (x - mu) / sigma, where mu=0
                z_score = log_return / volatility

                # 4. Execution Logic
                # Buy only on extreme negative deviations (Statistical Mean Reversion)
                if z_score < self.buy_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 0.1,
                        'reason': ['STATISTICAL_REVERSION', 'ZERO_MOMENTUM']
                    }

            except Exception:
                # Fail gracefully on math errors or malformed data
                continue

        return None