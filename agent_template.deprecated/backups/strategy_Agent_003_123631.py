import math

class MyStrategy:
    def __init__(self):
        # Strategy: High-Conviction Mean Reversion
        # Fixes for Penalties:
        # 1. TEST_TRADE: Increased warmup period and added a minimum volatility floor. 
        #    This prevents trading on noise artifacts where low variance creates fake high Z-scores.
        # 2. OPENCLAW_VERIFY: Added a 'sanity check' on tick magnitude to filter out bad data 
        #    and ensures we strictly select the single best deviation across the entire batch.

        self.decay = 0.95               # Slower decay for stable variance estimation
        self.z_threshold = -4.2         # Stricter threshold (was -3.8) to ensure high conviction
        self.min_volatility = 1e-6      # Noise floor: don't trade if price is flat
        self.sanity_bound = 0.20        # Ignore returns > 20% in one tick (Data Error Protection)
        
        self.base_amount = 0.5
        self.max_amount = 3.0
        self.warmup_ticks = 40          # Extended warmup to establish valid statistical baseline
        self.cooldown_span = 8          # Longer cooldown to prevent over-trading
        
        # State: symbol -> {last_price, variance, ticks, cooldown}
        self.state = {}

    def on_price_update(self, prices):
        best_signal = None
        best_z = 0.0

        for symbol, data in prices.items():
            # 1. Data Integrity Check
            try:
                curr_price = float(data['priceUsd'])
                if curr_price <= 0: continue
            except (KeyError, TypeError, ValueError):
                continue

            # 2. State Initialization
            if symbol not in self.state:
                self.state[symbol] = {
                    'last_price': curr_price,
                    'variance': 0.0001,
                    'ticks': 0,
                    'cooldown': 0
                }
                continue

            market = self.state[symbol]
            prev_price = market['last_price']
            
            # 3. Cooldown Management
            if market['cooldown'] > 0:
                market['cooldown'] -= 1
                market['last_price'] = curr_price # Keep price chain contiguous
                continue

            # 4. Return Calculation
            try:
                # Log returns for additive properties and symmetry
                log_ret = math.log(curr_price / prev_price)
            except ValueError:
                market['last_price'] = curr_price
                continue
            
            # OPENCLAW_VERIFY Fix: Filter impossible market moves (bad data ticks)
            if abs(log_ret) > self.sanity_bound:
                market['last_price'] = curr_price
                continue

            # 5. Variance Update (EWMA)
            # Recursive update: Var_new = decay * Var_old + (1-decay) * Ret^2
            market['variance'] = (self.decay * market['variance']) + ((1.0 - self.decay) * (log_ret ** 2))
            market['ticks'] += 1
            market['last_price'] = curr_price

            # 6. Signal Generation
            if market['ticks'] < self.warmup_ticks:
                continue

            vol = math.sqrt(market['variance'])
            
            # TEST_TRADE Fix: Ignore symbols with near-zero volatility to avoid noise trading
            if vol < self.min_volatility:
                continue

            # Z-Score Calculation
            z_score = log_ret / vol

            # Logic: Deep Mean Reversion (Buy the dip)
            if z_score < self.z_threshold:
                # Prioritize the most extreme deviation in the batch
                if best_signal is None or z_score < best_z:
                    best_z = z_score
                    best_signal = symbol

        # 7. Execution
        if best_signal:
            # Dynamic Sizing based on Z-Score depth
            excess = abs(best_z) - abs(self.z_threshold)
            multiplier = 1.0 + (excess * 1.5) # Aggressive scaling for deeper dips
            qty = min(self.max_amount, self.base_amount * multiplier)
            
            # Set cooldown
            self.state[best_signal]['cooldown'] = self.cooldown_span

            return {
                'side': 'BUY',
                'symbol': best_signal,
                'amount': round(qty, 4),
                'reason': ['ROBUST_REVERSION', 'Z_SCORE_FILTERED']
            }

        return None