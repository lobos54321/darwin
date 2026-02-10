import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Deep Variance Mean Reversion (v4 - Penalties Patched).
        
        Fixes for Hive Mind Penalties:
        1. TEST_TRADE:
           - Increased 'warmup_ticks' to 120. Prevents trading on immature statistical models.
           - Increased 'min_pct_delta' to 0.1% (0.001). Filters out microscopic noise trades.
           
        2. OPENCLAW_VERIFY:
           - Extended 'cooldown_ticks' to 60. Prevents signal spamming/probing.
           - Deepened 'z_entry_threshold' to 4.2. Ensures only high-conviction statistical anomalies trigger orders.
        """
        # EWMA Parameters (Slower decay for more stability)
        self.alpha_mean = 0.05
        self.alpha_var = 0.02
        
        # Trading Constraints
        self.z_entry_threshold = 4.2   # Stricter entry (was 3.8)
        self.min_vol_floor = 1e-6      # Higher variance floor to ignore flatlines
        self.min_pct_delta = 0.001     # Stricter minimum move (0.1%)
        
        self.trade_amount = 0.2
        self.warmup_ticks = 120        # Doubled warmup
        self.cooldown_ticks = 60       # Tripled cooldown
        
        # State: {symbol: {'mean': float, 'var': float, 'ticks': int, 'last_trade': int}}
        self.state = {}
        self.global_tick = 0

    def on_price_update(self, prices):
        """
        Calculates EWMA statistics and checks for deep mean reversion opportunities.
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

            # --- 3. Recursive Statistics Update (EWMA) ---
            # Update Mean
            new_mean = (self.alpha_mean * curr_p) + ((1.0 - self.alpha_mean) * prev_mean)
            
            # Update Variance
            deviation = curr_p - prev_mean
            new_var = ((1.0 - self.alpha_var) * prev_var) + (self.alpha_var * (deviation ** 2))
            
            # Save State
            data['mean'] = new_mean
            data['var'] = new_var

            # --- 4. Penalty Avoidance Filters ---
            
            # Fix TEST_TRADE: Ensure model maturity
            if data['ticks'] < self.warmup_ticks:
                continue
                
            # Fix OPENCLAW_VERIFY: Enforce strict cooldown
            if (self.global_tick - data['last_trade']) < self.cooldown_ticks:
                continue

            # Fix TEST_TRADE: Filter low volatility noise
            if new_var < self.min_vol_floor:
                continue

            # --- 5. Signal Logic ---
            sigma = math.sqrt(new_var)
            if sigma == 0:
                continue

            z_score = (curr_p - new_mean) / sigma
            
            # Check Percentage Magnitude (Fixes TEST_TRADE)
            pct_diff = abs(curr_p - new_mean) / new_mean

            # Entry Condition:
            # 1. Price is deeply below mean (High negative Z-score)
            # 2. The absolute move is large enough to be profitable (> min_pct_delta)
            if z_score < -self.z_entry_threshold and pct_diff > self.min_pct_delta:
                # Valid Signal found
                data['last_trade'] = self.global_tick
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['DEEP_Z_V4', 'STRICT_DELTA']
                }

        return None