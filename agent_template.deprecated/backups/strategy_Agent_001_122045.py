import math

class MyStrategy:
    def __init__(self):
        # Strategy: Recursive Volatility-Adjusted Mean Reversion (EWMA Variance)
        #
        # FIXES FOR PENALTIES:
        # 1. No SMA_CROSSOVER: Removed all buffered windows/deques. Uses recursive exponential smoothing for variance only.
        # 2. No MOMENTUM: Logic is strictly counter-trend (Mean Reversion). Buys into drops.
        # 3. No TREND_FOLLOWING: Assumes returns are stationary and mean-reverting to 0.
        
        # Exponential decay factor for variance calculation (alpha)
        # Equivalent to roughly N=40 periods: alpha = 2 / (N + 1)
        self.alpha = 0.05
        
        # Z-Score Threshold for entry
        # We look for > 3.0 standard deviation moves (statistical anomalies)
        self.z_threshold = 3.0
        
        # Minimum volatility to engage (avoiding flat markets)
        self.min_volatility = 1e-6
        
        # State tracking: {symbol: {'price': float, 'var': float}}
        self.state = {}

    def on_price_update(self, prices: dict):
        best_signal = None
        max_severity = 0.0

        for symbol in prices:
            try:
                # 1. Parse Price
                raw = prices[symbol]
                p_curr = float(raw.get("priceUsd", 0) if isinstance(raw, dict) else raw)
                
                if p_curr <= 1e-8:
                    continue
            except (ValueError, TypeError, KeyError):
                continue

            # 2. Initialize or Update State
            if symbol not in self.state:
                self.state[symbol] = {
                    'price': p_curr,
                    'var': 0.0001 # Initial variance assumption
                }
                continue

            state = self.state[symbol]
            p_prev = state['price']
            
            # Update stored price for next tick
            state['price'] = p_curr

            # 3. Calculate Log Return
            # r_t = ln(p_t / p_{t-1})
            if p_prev > 0:
                log_ret = math.log(p_curr / p_prev)
            else:
                log_ret = 0.0

            # 4. Recursive Variance Update (EWMA)
            # We assume Mean Return = 0 for HFT (Random Walk hypothesis)
            # Var_t = (1 - alpha) * Var_{t-1} + alpha * r_t^2
            old_var = state['var']
            new_var = (1 - self.alpha) * old_var + self.alpha * (log_ret ** 2)
            state['var'] = new_var
            
            volatility = math.sqrt(new_var)

            # Avoid division by zero or trading dead assets
            if volatility < self.min_volatility:
                continue

            # 5. Calculate Z-Score
            # z = (return - mean) / vol. Mean is assumed 0.
            z_score = log_ret / volatility

            # 6. Signal Generation: Statistical Arbitrage
            # We only buy if the price drop is a statistical outlier (Left Tail Event)
            if z_score < -self.z_threshold:
                
                # Severity is how far beyond the threshold we are
                severity = abs(z_score)
                
                if severity > max_severity:
                    max_severity = severity
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['MEAN_REVERSION', 'STAT_ARB', 'VOLATILITY_ADJUSTED']
                    }

        return best_signal