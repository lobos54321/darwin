import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Microstructural Mean Reversion (MMR)
        
        MECHANISM:
        Detects instantaneous liquidity gaps by calculating the Z-score of price returns
        relative to the pre-tick volatility regime.
        
        FIXES:
        1. NO SMA/TREND: Uses recursive return variance (GARCH-lite), no price averages.
        2. NO MOMENTUM: Pure counter-move logic (buying negative deviations).
        3. EXECUTION ORDER: Calculates Z-score against PRIOR variance to capture 
           sudden shocks before they normalize the volatility model.
        """
        # Decay factor for EWMA Variance (alpha = 0.05 equivalent)
        self.decay = 0.95
        
        # Stricter Threshold: -5.0 sigma event required (Elite Dip Buying)
        # Prevents engagement with standard noise or mild trends.
        self.z_threshold = -5.0
        
        # State tracking: {symbol: {'prev_price': float, 'variance': float}}
        self.stats = {}

    def on_price_update(self, prices):
        """
        HFT logic to identify and capture statistical anomalies.
        """
        for symbol in prices:
            try:
                # 1. Data Integrity Check
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                current_price = float(prices[symbol]['priceUsd'])
                if current_price <= 0:
                    continue

                # 2. State Initialization
                if symbol not in self.stats:
                    self.stats[symbol] = {
                        'prev_price': current_price,
                        'variance': 0.0001  # Seed variance
                    }
                    continue

                state = self.stats[symbol]
                prev_price = state['prev_price']

                # 3. Logarithmic Return Calculation
                # R_t = ln(P_t / P_t-1)
                log_return = math.log(current_price / prev_price)

                # 4. Anomaly Detection (Pre-Update)
                # We use the volatility from t-1 to evaluate the shock at t.
                # This fixes the dampening issue where updating variance first hides the shock.
                volatility = math.sqrt(state['variance'])
                
                # Avoid division by zero
                if volatility < 1e-9:
                    z_score = 0.0
                else:
                    z_score = log_return / volatility

                # 5. State Update (Recursive EWMA)
                # Var_t = lambda * Var_t-1 + (1 - lambda) * R_t^2
                # Zero-mean assumption is strictly enforced to avoid momentum drift.
                state['variance'] = (self.decay * state['variance']) + ((1 - self.decay) * (log_return ** 2))
                state['prev_price'] = current_price

                # 6. Execution Logic
                # Trigger only on statistically significant negative outliers.
                if z_score < self.z_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 0.1,
                        'reason': ['MICRO_REVERSION', 'LIQUIDITY_GAP']
                    }

            except Exception:
                # Robust error handling for production stability
                continue

        return None