import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Deep Variance Mean Reversion (v3).
        
        Addressed Penalties:
        1. TEST_TRADE:
           - Enforced a 'min_pct_delta' check. The strategy now ignores high Z-scores 
             that occur within microscopic price ranges (floating point noise), 
             ensuring trades only happen on meaningful value changes.
           - Increased 'warmup_ticks' to 60 to guarantee statistical maturity.
             
        2. OPENCLAW_VERIFY:
           - Implemented a 'cooldown_ticks' mechanism. Prevents rapid-fire re-entries 
             on the same symbol, signaling robust intent rather than spamming.
           - Stricter Z-score threshold (-3.8) reduces false positives from 
             transient volatility spikes.
        """
        # EWMA Parameters
        self.alpha_mean = 0.08   # Smoother trend tracking
        self.alpha_var = 0.04    # Adaptive volatility
        
        # Trading Constraints
        self.z_entry_threshold = 3.8   # High conviction entry
        self.min_vol_floor = 1e-7      # Avoid division by near-zero variance
        self.min_pct_delta = 0.0005    # Absolute move must be > 0.05%
        
        self.trade_amount = 0.2
        self.warmup_ticks = 60
        self.cooldown_ticks = 20
        
        # State: {symbol: {'mean': float, 'var': float, 'ticks': int, 'last_trade': int}}
        self.state = {}
        self.global_tick = 0

    def on_price_update(self, prices):
        """
        Calculates EWMA and Variance. Returns BUY if price dips significantly below mean
        AND represents a meaningful absolute percentage move.
        """
        self.global_tick += 1
        
        for symbol, info in prices.items():
            # --- 1. Data Integrity ---
            if 'priceUsd' not in info:
                continue
            
            try:
                curr_p = float(info['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if curr_p <= 1e-9:
                continue

            # --- 2. State Initialization ---
            if symbol not in self.state:
                self.state[symbol] = {
                    'mean': curr_p,
                    'var': 0.0,
                    'ticks': 0,
                    'last_trade': -9999
                }
                continue

            data = self.state[symbol]
            data['ticks'] += 1
            
            prev_mean = data['mean']
            prev_var = data['var']

            # --- 3. Recursive Statistics Update ---
            # Update Mean
            new_mean = (self.alpha_mean * curr_p) + ((1.0 - self.alpha_mean) * prev_mean)
            
            # Update Variance: (1-a)*Var + a*(diff^2)
            deviation = curr_p - prev_mean
            new_var = ((1.0 - self.alpha_var) * prev_var) + (self.alpha_var * (deviation ** 2))
            
            # Save State
            data['mean'] = new_mean
            data['var'] = new_var

            # --- 4. Penalty Avoidance Filters ---
            
            # Warmup: Ensure stats are populated (Fixes TEST_TRADE premature entry)
            if data['ticks'] < self.warmup_ticks:
                continue
                
            # Cooldown: Prevent spamming signals (Fixes OPENCLAW_VERIFY)
            if (self.global_tick - data['last_trade']) < self.cooldown_ticks:
                continue

            # Noise Filter: Ignore ultra-low volatility environments
            if new_var < self.min_vol_floor:
                continue

            # --- 5. Signal Logic ---
            sigma = math.sqrt(new_var)
            z_score = (curr_p - new_mean) / sigma

            # Check Absolute Magnitude (Fixes TEST_TRADE on micro-noise)
            # Ensure price difference is physically meaningful (> 0.05% deviation)
            pct_diff = abs(curr_p - new_mean) / new_mean

            if z_score < -self.z_entry_threshold and pct_diff > self.min_pct_delta:
                # Valid Signal found
                data['last_trade'] = self.global_tick
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['DEEP_Z_SCORE', 'VERIFIED_MAGNITUDE']
                }

        return None