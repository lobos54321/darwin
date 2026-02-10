import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Microstructural Mean Reversion
        
        LOGIC:
        Identifies instantaneous liquidity gaps (flash crashes) by calculating the Z-score 
        of log returns normalized by a recursive volatility estimate.
        
        COMPLIANCE:
        - No SMA/Trend: Uses instantaneous return variance (GARCH-style).
        - No Momentum: Strictly buys negative deviations (counter-move).
        - Stricter Dip Buying: High sigma threshold to avoid noise.
        """
        # Volatility decay factor (0.94 ~ 16 tick half-life)
        self.decay = 0.94
        
        # Stricter Threshold: Requires a 4.5 sigma deviation
        # Ensures we only trade significant microstructure breakdowns
        self.z_threshold = 4.5
        
        # Minimum volatility clamp to prevent division by zero or trading flat lines
        self.min_vol = 1e-8
        
        # State tracking: {symbol: {'prev_price': float, 'variance': float}}
        self.stats = {}

    def on_price_update(self, prices):
        """
        Process price updates and check for statistical arbitrage opportunities.
        """
        for symbol in prices:
            try:
                # 1. Data Parsing & Validation
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                try:
                    current_price = float(prices[symbol]['priceUsd'])
                except ValueError:
                    continue
                    
                if current_price <= 0:
                    continue

                # 2. State Initialization
                if symbol not in self.stats:
                    self.stats[symbol] = {
                        'prev_price': current_price,
                        'variance': 0.0001  # Initial variance assumption
                    }
                    continue

                state = self.stats[symbol]
                prev_price = state['prev_price']

                # 3. Log Return Calculation
                # r_t = ln(p_t / p_{t-1})
                log_return = math.log(current_price / prev_price)

                # 4. Volatility Estimation (Ex-Ante)
                # Calculate Z-score using PRIOR variance to correctly measure the current shock
                volatility = math.sqrt(state['variance'])
                
                if volatility < self.min_vol:
                    z_score = 0.0
                else:
                    z_score = log_return / volatility

                # 5. State Update (EWMA)
                # var_t = lambda * var_{t-1} + (1 - lambda) * r_t^2
                state['variance'] = (self.decay * state['variance']) + \
                                    ((1.0 - self.decay) * (log_return ** 2))
                state['prev_price'] = current_price

                # 6. Execution Logic
                # Buy only on extreme negative outliers (Mean Reversion)
                if z_score < -self.z_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 0.1,
                        'reason': ['MEAN_REVERSION', 'LIQUIDITY_VOID']
                    }

            except Exception:
                # Robust error handling ensures the loop continues for other symbols
                continue

        return None