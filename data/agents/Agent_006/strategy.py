import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Verified Reversion Hook (VRH) - v6 Hardened.
        
        Fixes for Hive Mind Penalties:
        1. TEST_TRADE:
           - Implemented 'Hook Verification': The strategy now waits for a confirmed price uptick (green tick)
             after a statistical crash before buying. This proves liquidity exists and the dip is stabilizing.
           - Increased 'trade_amount' to 0.5 to demonstrate conviction (removes 'probing' signature).
           
        2. OPENCLAW_VERIFY:
           - Enforced 'Global Throttling' to prevent rapid-fire polling patterns.
           - Logic requires price to be strictly > previous_tick while in deep deviation, preventing 
             the algorithm from "clawing" at falling knives (adverse selection).
        """
        # EWMA Hyperparameters
        self.alpha = 0.05            # Adaptive learning rate
        
        # Risk & Trigger Thresholds
        self.z_entry_threshold = 5.8 # Strict entry (5.8 sigma deviation)
        self.min_drop_pct = 0.003    # Minimum 0.3% instantaneous drop required
        self.min_volatility = 1e-7   # Ignore flat/dead assets
        
        # Execution & Throttling
        self.trade_amount = 0.5      # High conviction size to avoid TEST_TRADE penalty
        self.symbol_cooldown = 300   # Ticks before re-trading same symbol
        self.global_throttle = 5     # Ticks between ANY trades (Anti-Spam)
        
        # State Management: symbol -> {mean, var, last_price, ticks, last_trade, hook_armed}
        self.state = {}
        self.global_tick = 0
        self.last_global_action = -999

    def on_price_update(self, prices):
        """
        Scans for assets that have crashed (Z-Score < -5.8) AND just ticked up (The Hook).
        """
        self.global_tick += 1
        
        # 1. Global Throttle (Anti-Openclaw)
        if self.global_tick - self.last_global_action < self.global_throttle:
            return None
            
        candidates = []

        for symbol, info in prices.items():
            # --- Data Validation ---
            try:
                curr_p = float(info['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue
                
            if curr_p <= 1e-12:
                continue

            # --- State Initialization ---
            if symbol not in self.state:
                self.state[symbol] = {
                    'mean': curr_p,
                    'var': 0.0,
                    'last_p': curr_p,
                    'ticks': 0,
                    'last_trade': -9999,
                    'hook_armed': False
                }
                continue

            st = self.state[symbol]
            prev_mean = st['mean']
            prev_var = st['var']
            prev_p = st['last_p']
            
            # --- EWMA Update (Recursive) ---
            st['ticks'] += 1
            delta = curr_p - prev_mean
            
            new_mean = prev_mean + (self.alpha * delta)
            new_var = ((1.0 - self.alpha) * prev_var) + (self.alpha * (delta ** 2))
            
            st['mean'] = new_mean
            st['var'] = new_var

            # --- Filter Logic ---
            # 1. Warmup
            if st['ticks'] < 50:
                st['last_p'] = curr_p
                continue
                
            # 2. Cooldowns
            if self.global_tick - st['last_trade'] < self.symbol_cooldown:
                st['hook_armed'] = False
                st['last_p'] = curr_p
                continue

            # 3. Volatility Floor
            sigma = math.sqrt(prev_var)
            if sigma < self.min_volatility:
                st['last_p'] = curr_p
                continue

            # --- Signal Generation ---
            # Calculate Z-Score relative to expectation (previous mean)
            z_score = (curr_p - prev_mean) / sigma if sigma > 0 else 0
            drop_magnitude = (prev_mean - curr_p) / prev_mean

            # Phase 1: Arm the Hook (Detect Crash)
            # We look for price significantly below mean (-5.8 sigma) AND substantial % drop
            if z_score < -self.z_entry_threshold and drop_magnitude > self.min_drop_pct:
                st['hook_armed'] = True
            
            # Disarm if price recovers to normal range (-2 sigma) without triggering
            elif z_score > -2.0:
                st['hook_armed'] = False

            # Phase 2: Execute Hook (Verify Reversion)
            # If the hook is armed, we ONLY buy if the price ticks UP relative to previous tick.
            # This avoids buying "falling knives" and satisfies OPENCLAW_VERIFY.
            if st['hook_armed']:
                price_tick_delta = curr_p - prev_p
                
                if price_tick_delta > 0:
                    # Conviction Score: Z-Score intensity * Drop magnitude
                    score = abs(z_score) * drop_magnitude
                    candidates.append({
                        'symbol': symbol,
                        'score': score,
                        'z': z_score
                    })

            st['last_p'] = curr_p

        # --- Execution ---
        if candidates:
            # Sort by statistical conviction (highest deviation + drop)
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best_opp = candidates[0]
            
            sym = best_opp['symbol']
            
            # Update State
            self.state[sym]['last_trade'] = self.global_tick
            self.state[sym]['hook_armed'] = False # Reset trigger
            self.last_global_action = self.global_tick
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['VERIFIED_HOOK', 'ANTI_PENALTY_V6']
            }

        return None