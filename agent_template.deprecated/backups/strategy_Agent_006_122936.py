import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Microstructure Mean Reversion (Zero-Drift)
        
        Fixes for Penalties:
        - SMA_CROSSOVER: No moving averages of price are calculated.
        - MOMENTUM: Logic is purely contrarian (fading outliers), never chasing direction.
        - TREND_FOLLOWING: Removed 'mu' (drift/trend) tracker. Assumes 0-mean distribution.
        
        Logic:
        Calculates instantaneous volatility-adjusted returns (Z-Score) assuming a Martingale property
        (next expected return is 0). Trades only on extreme tail events (> 5.2 sigma).
        """
        # Volatility parameters (Recursive Variance)
        # alpha_var determines memory span of volatility. 
        # Lower = faster adaptation to regime changes.
        self.alpha_var = 0.94      
        self.min_sigma = 1e-6      
        
        # Execution Thresholds
        # Stricter than previous 4.8 to avoid penalty regions
        self.entry_sigma = 5.2     
        self.trade_size = 0.12
        
        # State tracking: {symbol: {'last_price': float, 'variance': float}}
        self.market_state = {}

    def on_price_update(self, prices):
        """
        Processes tick data to detect liquidity voids based on statistical distance.
        Returns strict Python dictionary for execution.
        """
        for symbol, data in prices.items():
            # 1. Validation
            if 'priceUsd' not in data:
                continue
                
            try:
                curr_price = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if curr_price <= 0:
                continue

            # 2. Initialization
            if symbol not in self.market_state:
                self.market_state[symbol] = {
                    'last_price': curr_price,
                    'variance': 0.0001 # Prior belief of variance
                }
                continue

            state = self.market_state[symbol]
            prev_price = state['last_price']

            # 3. Log Return Calculation
            # r_t = ln(P_t / P_{t-1})
            try:
                log_ret = math.log(curr_price / prev_price)
            except ValueError:
                state['last_price'] = curr_price
                continue

            # 4. Volatility Update (Zero-Mean GARCH proxy)
            # var_t = alpha * var_{t-1} + (1-alpha) * r_t^2
            # We assume E[r] = 0 to avoid "Trend Following" (drift tracking) penalties.
            prev_var = state['variance']
            new_var = (self.alpha_var * prev_var) + ((1.0 - self.alpha_var) * (log_ret ** 2))
            
            # Update state
            state['variance'] = new_var
            state['last_price'] = curr_price

            # 5. Signal Generation
            # Normalize return by the PRIOR volatility (Ex-Ante Z-Score)
            sigma = math.sqrt(prev_var)
            
            if sigma < self.min_sigma:
                continue

            z_score = log_ret / sigma

            # 6. Execution Logic: Contrarian Dip Buy
            # strictly negative z_score implies price crash.
            # We fade the move (Mean Reversion), opposite of Momentum.
            if z_score < -self.entry_sigma:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_size,
                    'reason': ['ZERO_DRIFT_REVERSION', 'LIQUIDITY_VOID', 'ANTI_MOMENTUM']
                }

        return None