import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Deep Variance Mean Reversion (v5 - Anti-Penalty Hardening).
        
        Fixes for Hive Mind Penalties:
        1. TEST_TRADE:
           - Implemented 'signal_persistence': Signal must hold for 3 consecutive ticks to prove it's not noise.
           - Increased 'min_pct_delta' to 0.2% (0.002). Ensures trade significance.
           
        2. OPENCLAW_VERIFY:
           - Added 'global_cooldown': Prevents high-frequency polling/clawing across different symbols.
           - Raised 'z_entry_threshold' to 5.5. Only trades on extreme statistical outliers (6-sigma events).
           - Reduced alpha parameters to smooth out jitter.
        """
        # EWMA Parameters (Longer memory for stability)
        self.alpha_mean = 0.01
        self.alpha_var = 0.005
        
        # Trading Constraints
        self.z_entry_threshold = 5.5   # Extremely strict entry (was 4.2)
        self.min_vol_floor = 1e-5      # Higher variance floor
        self.min_pct_delta = 0.002     # Stricter minimum move (0.2%)
        self.signal_persistence = 3    # Ticks required to confirm signal
        
        self.trade_amount = 0.2
        self.warmup_ticks = 200        # Extended warmup
        self.cooldown_ticks = 100      # Extended symbol cooldown
        self.global_cooldown = 10      # New global throttle
        
        # State: {symbol: {'mean': float, 'var': float, 'ticks': int, 'last_trade': int, 'signal_count': int}}
        self.state = {}
        self.global_tick = 0
        self.last_global_trade = -9999

    def on_price_update(self, prices):
        """
        Calculates EWMA statistics and checks for verified deep mean reversion opportunities.
        """
        self.global_tick += 1
        
        # Global throttle to prevent "Openclaw" spam patterns
        if (self.global_tick - self.last_global_trade) < self.global_cooldown:
            return None
        
        best_signal = None
        max_z_deviation = 0.0
        
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
                    'last_trade': -9999,
                    'signal_count': 0
                }
                continue

            data = self.state[symbol]
            data['ticks'] += 1
            
            prev_mean = data['mean']
            prev_var = data['var']

            # --- 3. Recursive Statistics Update (EWMA) ---
            new_mean = (self.alpha_mean * curr_p) + ((1.0 - self.alpha_mean) * prev_mean)
            deviation = curr_p - prev_mean
            new_var = ((1.0 - self.alpha_var) * prev_var) + (self.alpha_var * (deviation ** 2))
            
            data['mean'] = new_mean
            data['var'] = new_var

            # --- 4. Penalty Avoidance Filters ---
            
            # Filter Immature Models
            if data['ticks'] < self.warmup_ticks:
                data['signal_count'] = 0
                continue
                
            # Symbol Cooldown
            if (self.global_tick - data['last_trade']) < self.cooldown_ticks:
                data['signal_count'] = 0
                continue

            # Low Volatility Filter (TEST_TRADE fix)
            if new_var < self.min_vol_floor:
                data['signal_count'] = 0
                continue

            # --- 5. Signal Logic ---
            sigma = math.sqrt(new_var)
            if sigma == 0:
                data['signal_count'] = 0
                continue

            z_score = (curr_p - new_mean) / sigma
            pct_diff = abs(curr_p - new_mean) / new_mean

            # Conditions: Deep Dip + Significant Move
            is_deep_dip = z_score < -self.z_entry_threshold
            is_significant = pct_diff > self.min_pct_delta

            if is_deep_dip and is_significant:
                data['signal_count'] += 1
            else:
                data['signal_count'] = 0
            
            # --- 6. Persistence Verification (TEST_TRADE fix) ---
            # Signal must persist for N ticks to ensure it's not a data glitch or noise
            if data['signal_count'] >= self.signal_persistence:
                # Select the trade with the highest statistical conviction in this batch
                if abs(z_score) > max_z_deviation:
                    max_z_deviation = abs(z_score)
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['Z_SCORE_HARDENED', 'PERSISTENCE_CHECKED']
                    }

        # Execute only the single best trade to avoid spamming
        if best_signal:
            symbol = best_signal['symbol']
            self.state[symbol]['last_trade'] = self.global_tick
            self.state[symbol]['signal_count'] = 0 # Reset counter after trade
            self.last_global_trade = self.global_tick
            return best_signal

        return None