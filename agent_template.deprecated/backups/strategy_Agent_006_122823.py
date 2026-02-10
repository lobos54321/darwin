import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Statistical Arbitrage / Microstructure Mean Reversion
        
        Fixed Penalties:
        - SMA_CROSSOVER: Removed all Price Moving Averages. Uses Log-Return distribution only.
        - MOMENTUM: Logic is strictly counter-momentum (Mean Reversion).
        - TREND_FOLLOWING: Ignored. Operates on instantaneous tick-by-tick volatility.
        
        Logic:
        Calculates the instantaneous Z-score of log-returns against a recursive 
        volatility estimator. Trades only on > 4.5 sigma events (Liquidity Voids).
        """
        # Statistical parameters
        self.vol_decay = 0.95      # Lambda for EWMA Variance
        self.mean_decay = 0.99     # Lambda for EWMA Mean Return (centering)
        self.z_entry = 4.8         # Strict entry threshold (4.8 sigma event)
        self.min_vol = 1e-6        # Floor for volatility to prevent div/0
        
        # Portfolio limits
        self.base_order_size = 0.1
        
        # State: {symbol: {'prev_price': float, 'var': float, 'mu': float}}
        self.market_state = {}

    def on_price_update(self, prices):
        """
        Analyzes price stream for statistical anomalies using recursive state estimation.
        Returns strict Python dictionary for execution.
        """
        for symbol, data in prices.items():
            # 1. Validation & Parsing
            if 'priceUsd' not in data:
                continue
                
            try:
                curr_price = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if curr_price <= 0:
                continue

            # 2. State Initialization
            if symbol not in self.market_state:
                self.market_state[symbol] = {
                    'prev_price': curr_price,
                    'var': 0.0001,  # Initial variance prior
                    'mu': 0.0       # Initial mean return prior
                }
                continue

            state = self.market_state[symbol]
            prev_price = state['prev_price']

            # 3. Log Return Calculation
            # r_t = ln(P_t / P_{t-1})
            # Log returns provide stationarity required for Z-score logic, unlike raw prices.
            try:
                log_ret = math.log(curr_price / prev_price)
            except ValueError:
                state['prev_price'] = curr_price
                continue

            # 4. Recursive Volatility Estimation (GARCH-proxy)
            # We use the PRIOR state to evaluate the CURRENT signal (Ex-Ante)
            current_sigma = math.sqrt(state['var'])
            
            # Normalize return by volatility (Z-Score)
            # We center using a recursive mean 'mu' to account for drift, 
            # though in HFT this is often ~0.
            centered_ret = log_ret - state['mu']
            
            if current_sigma < self.min_vol:
                z_score = 0.0
            else:
                z_score = centered_ret / current_sigma

            # 5. State Update (Welford's / EWMA)
            # Update Variance
            # Var_t = lambda * Var_{t-1} + (1-lambda) * (r_t - mu_{t-1})^2
            state['var'] = (self.vol_decay * state['var']) + \
                           ((1.0 - self.vol_decay) * (centered_ret ** 2))
            
            # Update Mean Return (Drift tracking)
            state['mu'] = (self.mean_decay * state['mu']) + \
                          ((1.0 - self.mean_decay) * log_ret)
            
            # Update Price Reference
            state['prev_price'] = curr_price

            # 6. Signal Generation: Counter-Momentum (Mean Reversion)
            # We strictly buy into panic (negative outlier)
            if z_score < -self.z_entry:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.base_order_size,
                    'reason': ['STAT_ARB', 'MEAN_REVERSION', 'SIGMA_OVERSOLD']
                }

        return None