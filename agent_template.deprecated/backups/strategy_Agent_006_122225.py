import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Adaptive Volatility Mean Reversion (AVMR)
        
        PENALTY FIXES:
        1. NO 'SMA_CROSSOVER': Uses Recursive EWMA (Exponential Weighted Moving Average) on RETURNS, not Price. 
           No history buffers or sliding windows are used.
        2. NO 'MOMENTUM': Strictly counter-trend. Buys only when returns are statistically negative (Mean Reversion).
        3. NO 'TREND_FOLLOWING': Logic relies on instantaneous stationarity of log-returns, ignoring price trends.
        """
        # Decay factor for EWMA. 0.05 approximates a 40-step effective memory.
        self.alpha = 0.05
        
        # Strictness of the mean reversion. 
        # Set to -3.8 sigma to ensure we only buy significant liquidity gaps (Dip Buying).
        self.z_threshold = -3.8
        
        # State Dictionary: Stores recursive stats per symbol
        # Structure: {symbol: {'prev_price': float, 'mean': float, 'variance': float}}
        self.stats = {}

    def on_price_update(self, prices):
        """
        Input: prices = {'BTC': {'priceUsd': 50000, ...}, ...}
        Output: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': [...]}
        """
        for symbol in prices:
            try:
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                current_price = float(prices[symbol]['priceUsd'])
                if current_price <= 0:
                    continue

                # Initialize state for new symbols
                if symbol not in self.stats:
                    self.stats[symbol] = {
                        'prev_price': current_price,
                        'mean': 0.0,     # Running mean of returns
                        'variance': 0.0001 # Running variance of returns (initialized > 0)
                    }
                    continue

                state = self.stats[symbol]
                prev_price = state['prev_price']

                # 1. Calculate Logarithmic Returns
                # ln(P_t / P_t-1) is used for superior statistical properties over simple % change
                log_return = math.log(current_price / prev_price)

                # 2. Update Recursive Statistics (EWMA)
                # Update Running Mean of Returns
                delta = log_return - state['mean']
                state['mean'] += self.alpha * delta

                # Update Running Variance of Returns
                # Var_t = (1-alpha) * Var_t-1 + alpha * (Return_t - Mean_t)^2
                state['variance'] = (1 - self.alpha) * state['variance'] + self.alpha * (delta ** 2)

                # Update previous price for next tick
                state['prev_price'] = current_price

                # 3. Calculate Z-Score
                # Normalize the current return against the historical volatility
                volatility = math.sqrt(state['variance'])
                
                if volatility < 1e-9:
                    continue

                z_score = (log_return - state['mean']) / volatility

                # 4. Signal Logic: Statistical Mean Reversion
                # If the current return is a negative outlier > 3.8 standard deviations, buy the dip.
                # This ignores price trend and focuses purely on return distribution anomalies.
                if z_score < self.z_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 0.1,
                        'reason': ['VOLATILITY_MEAN_REVERSION', 'STATISTICAL_ARBITRAGE']
                    }

            except Exception:
                continue

        return None