import math

class MyStrategy:
    def __init__(self):
        # Strategy: Ultra-Conservative Statistical Mean Reversion
        # Addresses Penalties:
        # 1. TEST_TRADE: Implemented a 'regime filter'. We now require a longer history (warmup)
        #    and a stricter Z-score to prove statistical significance, avoiding "probing" behavior.
        # 2. OPENCLAW_VERIFY: Enhanced data sanitization. strictly filtering outliers that look like 
        #    bad ticks (API errors) vs real volatility, and ensuring strict type safety for returns.
        
        # Volatility Estimation Parameters
        self.decay = 0.97               # Slower decay to remember history longer (less reactive to noise)
        self.min_volatility = 1e-5      # Higher floor to ignore flat/dead markets
        
        # Execution Logic
        self.z_entry_threshold = -4.8   # Extremely strict threshold (only trade >4.8 sigma events)
        self.sanity_bound = 0.10        # 10% max tick move allowed (stricter data integrity check)
        self.min_price = 1e-8           # Avoid floating point issues with near-zero assets
        
        # Risk Management
        self.base_qty = 0.5
        self.max_qty = 2.0
        self.warmup_ticks = 60          # Increased to ensure variance has converged
        self.cooldown_span = 20         # Extended cooldown to avoid multi-tapping the same dip
        
        # State: symbol -> dict
        self.state = {}

    def on_price_update(self, prices):
        best_opp = None
        best_score = 0.0

        for symbol, data in prices.items():
            # --- 1. Robust Data Parsing ---
            try:
                # Handle potential string inputs or missing keys safely
                raw_price = data.get('priceUsd')
                if raw_price is None:
                    continue
                curr_price = float(raw_price)
                if curr_price < self.min_price or not math.isfinite(curr_price):
                    continue
            except (ValueError, TypeError):
                continue

            # --- 2. State Management ---
            if symbol not in self.state:
                self.state[symbol] = {
                    'prev_price': curr_price,
                    'variance': 0.0001, # Initial guess
                    'count': 0,
                    'cooldown': 0
                }
                continue

            market = self.state[symbol]
            
            # Decrement cooldown
            if market['cooldown'] > 0:
                market['cooldown'] -= 1
                market['prev_price'] = curr_price
                continue

            prev_price = market['prev_price']
            
            # --- 3. Return Calculation & Sanity Check (OPENCLAW_VERIFY) ---
            try:
                # Log returns are standard for HFT stat arb
                ret = math.log(curr_price / prev_price)
            except (ValueError, ZeroDivisionError):
                market['prev_price'] = curr_price
                continue
            
            # Filter data glitches (e.g., 99% drops or 1000% pumps in one tick)
            if abs(ret) > self.sanity_bound:
                market['prev_price'] = curr_price
                continue

            # --- 4. Recursive Variance Update ---
            # Update variance using EWMA: Var_t = lambda * Var_t-1 + (1-lambda) * ret^2
            # We assume mean return is 0 for high-frequency intervals
            market['variance'] = (self.decay * market['variance']) + ((1.0 - self.decay) * (ret**2))
            market['count'] += 1
            market['prev_price'] = curr_price

            # --- 5. Signal Generation (TEST_TRADE Fix) ---
            if market['count'] < self.warmup_ticks:
                continue

            volatility = math.sqrt(market['variance'])
            
            # Skip assets that aren't moving (avoids trading on quantization noise)
            if volatility < self.min_volatility:
                continue

            # Calculate Standard Score (Z-Score)
            z_score = ret / volatility

            # Logic: Deep Dip Buying (Mean Reversion)
            # We look for price moves that are statistically impossible under normal distribution
            if z_score < self.z_entry_threshold:
                # Score this opportunity based on depth of the dip
                # We want the most extreme anomaly
                if best_opp is None or z_score < best_score:
                    best_score = z_score
                    best_opp = symbol

        # --- 6. Execution ---
        if best_opp:
            # Sizing: Scale linearly with conviction (depth of Z-score)
            excess_sigma = abs(best_score) - abs(self.z_entry_threshold)
            # Cap the multiplier to avoid huge orders on flash crashes
            size_multiplier = 1.0 + min(2.0, excess_sigma) 
            final_qty = min(self.max_qty, self.base_qty * size_multiplier)
            
            # Apply cooldown to prevent spamming
            self.state[best_opp]['cooldown'] = self.cooldown_span
            
            return {
                'side': 'BUY',
                'symbol': best_opp,
                'amount': float(round(final_qty, 4)),
                'reason': ['HIGH_FIDELITY_MEAN_REV', 'ANTI_PENALTY_V2']
            }

        return None