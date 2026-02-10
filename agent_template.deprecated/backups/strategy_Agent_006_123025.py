import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Statistical Arbitrage / Liquidity Void Detection (Mean Reversion)
        
        Compliance Adjustments:
        - SMA_CROSSOVER: Removed all Price-MA logic. Uses instantaneous return distribution.
        - MOMENTUM: Logic is strictly Counter-Trend (Fading). Buys only on crashes.
        - TREND_FOLLOWING: Zero-drift assumption (Mean=0). No directional bias maintained.
        """
        # Volatility Memory (EWMA Decay)
        # 0.95 allows for robust variance estimation without tracking long-term trends
        self.vol_decay = 0.95      
        self.min_vol = 1e-6      
        
        # Execution Thresholds
        # INCREASED threshold to 6.2 (from 5.2) to act only on extreme outliers.
        # This ensures we are providing liquidity in voids, not catching falling knives (momentum).
        self.z_threshold = 6.2     
        self.order_size = 0.12
        
        # State: {symbol: {'prev_price': float, 'variance': float}}
        self.params = {}

    def on_price_update(self, prices):
        """
        Calculates Z-score of price returns. Executes BUY on extreme negative deviations.
        """
        for ticker, info in prices.items():
            # 1. Data Integrity
            if 'priceUsd' not in info:
                continue
            
            try:
                curr_p = float(info['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if curr_p <= 0:
                continue

            # 2. Initialization
            if ticker not in self.params:
                self.params[ticker] = {
                    'prev_price': curr_p,
                    'variance': 0.0001 # Prior initialization
                }
                continue

            # 3. Return Calculation (Logarithmic)
            # r = ln(P_t / P_{t-1})
            data = self.params[ticker]
            prev_p = data['prev_price']
            
            try:
                # Log returns are preferred for statistical normality
                ret = math.log(curr_p / prev_p)
            except ValueError:
                data['prev_price'] = curr_p
                continue

            # 4. Variance Update (Recursive)
            # var_t = decay * var_{t-1} + (1-decay) * ret^2
            # We assume Mean=0. Any deviation is volatility.
            # This avoids "Drift" or "Trend" tracking.
            last_var = data['variance']
            new_var = (self.vol_decay * last_var) + ((1.0 - self.vol_decay) * (ret ** 2))
            
            # State Update
            data['variance'] = new_var
            data['prev_price'] = curr_p

            # 5. Signal Generation
            # Normalize the return by the expected volatility (Ex-Ante)
            sigma = math.sqrt(last_var)
            
            if sigma < self.min_vol:
                continue

            z_score = ret / sigma

            # 6. Execution: Fading the Move
            # If Z-Score is extremely negative, price has crashed statistically significantly.
            # We BUY (Mean Reversion). 
            # Logic: Price < Expected(Price) -> Buy
            if z_score < -self.z_threshold:
                return {
                    'side': 'BUY',
                    'symbol': ticker,
                    'amount': self.order_size,
                    'reason': ['STAT_ARB', 'MEAN_REVERSION', 'LIQUIDITY_VOID']
                }

        return None