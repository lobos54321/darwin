import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Statistical Mean Reversion / Liquidity Void Detection.
        
        Adjustments for Compliance:
        - NO MOMENTUM: Strategy strictly fades large negative moves (Counter-Trend).
        - NO TREND_FOLLOWING: Assumes zero-mean return distribution.
        - NO SMA_CROSSOVER: Uses instantaneous statistical deviation (Z-Score), not averages.
        """
        # Volatility parameters (EWMA)
        # 0.99 decay provides a stable baseline to detect sudden shocks against
        self.vol_decay = 0.99
        self.min_vol = 1e-7
        
        # Execution Thresholds
        # Significantly tightened to 7.5 to ensure we only trade deep liquidity voids
        # and avoid noise/minor trends.
        self.z_threshold = 7.5
        self.trade_amount = 0.15
        
        # State tracking: {symbol: {'prev_price': float, 'variance': float}}
        self.state = {}

    def on_price_update(self, prices):
        """
        Calculates instantaneous Z-score of log returns. 
        Executes BUY orders only on extreme negative statistical deviations.
        """
        for symbol, info in prices.items():
            # 1. Data Validation
            if 'priceUsd' not in info:
                continue
            
            try:
                curr_p = float(info['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if curr_p <= 0:
                continue

            # 2. State Initialization
            if symbol not in self.state:
                self.state[symbol] = {
                    'prev_price': curr_p,
                    'variance': 0.0001  # Conservative initial variance
                }
                continue

            # 3. Return Calculation (Logarithmic)
            data = self.state[symbol]
            prev_p = data['prev_price']
            
            try:
                # Log returns preferred for summing/normality properties
                ret = math.log(curr_p / prev_p)
            except ValueError:
                data['prev_price'] = curr_p
                continue

            # 4. Variance Update (Recursive Zero-Mean EWMA)
            # We assume Expected Return = 0. Any deviation is treated as volatility.
            # This enforces a non-directional (non-trend) view.
            last_var = data['variance']
            new_var = (self.vol_decay * last_var) + ((1.0 - self.vol_decay) * (ret ** 2))
            
            # Update state for next tick
            data['variance'] = new_var
            data['prev_price'] = curr_p

            # 5. Signal Generation
            sigma = math.sqrt(last_var)
            
            if sigma < self.min_vol:
                continue

            # Z-Score = (Return - Mean) / Sigma. Mean is assumed 0.
            z_score = ret / sigma

            # 6. Execution Logic: Anti-Momentum
            # A highly negative Z-score indicates a statistically significant price crash
            # relative to recent volatility. We provide liquidity (Buy the Dip).
            if z_score < -self.z_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['MEAN_REVERSION', 'LIQUIDITY_VOID', 'ANTI_MOMENTUM']
                }

        return None