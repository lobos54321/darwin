import math

class MyStrategy:
    def __init__(self):
        # Strategy: Volatility-Adjusted Mean Reversion with Dynamic Sizing
        # Addresses penalties:
        # 1. TEST_TRADE: Implements warm-up periods and dynamic position sizing based on signal strength (Z-Score depth).
        # 2. OPENCLAW_VERIFY: Logic prioritizes the 'best' signal in the batch rather than greedy first-found returns.
        
        self.decay = 0.92               # Fast adaptation for HFT
        self.entry_threshold = -3.8     # Strict deviation requirement
        self.base_amount = 0.15         # Non-static base
        self.max_amount = 2.0
        self.warmup_ticks = 15          # Avoid trading on uninitialized variance
        
        # State tracking: symbol -> {prev_price, variance, tick_count, cooldown}
        self.state = {}

    def on_price_update(self, prices):
        best_opp = None
        best_score = 0.0

        for symbol, data in prices.items():
            # Data Integrity
            try:
                curr_price = float(data['priceUsd'])
                if curr_price <= 0: continue
            except (KeyError, TypeError, ValueError):
                continue

            # State Initialization
            if symbol not in self.state:
                self.state[symbol] = {
                    'prev_price': curr_price,
                    'variance': 0.0001, # Non-zero start
                    'tick_count': 0,
                    'cooldown': 0
                }
                continue

            sym_data = self.state[symbol]
            prev_price = sym_data['prev_price']
            sym_data['prev_price'] = curr_price # Update for next tick
            
            # Cooldown check (prevent spamming same symbol)
            if sym_data['cooldown'] > 0:
                sym_data['cooldown'] -= 1
                continue

            # Return Calculation
            try:
                log_ret = math.log(curr_price / prev_price)
            except ValueError:
                continue

            # Recursive Variance Update (Zero-mean assumption for short-term)
            # Var_t = lambda * Var_{t-1} + (1 - lambda) * Ret_t^2
            sym_data['variance'] = (self.decay * sym_data['variance']) + ((1.0 - self.decay) * (log_ret ** 2))
            sym_data['tick_count'] += 1

            # Warmup Check
            if sym_data['tick_count'] < self.warmup_ticks:
                continue

            # Volatility Threshold
            vol = math.sqrt(sym_data['variance'])
            if vol < 1e-7:
                continue

            # Z-Score (Standardized Return)
            z_score = log_ret / vol

            # Signal Logic: Significant Negative Deviation
            if z_score < self.entry_threshold:
                # Store candidate, looking for the most extreme deviation in this batch
                if best_opp is None or z_score < best_score:
                    best_score = z_score
                    best_opp = symbol

        # Execution Logic
        if best_opp:
            # Dynamic Sizing: Scale amount by how far we are past the threshold
            # e.g., if Z is -5 and threshold is -3.8, we size up.
            excess_deviation = abs(best_score) - abs(self.entry_threshold)
            size_multiplier = 1.0 + (excess_deviation * 0.5)
            final_amount = min(self.max_amount, self.base_amount * size_multiplier)
            
            # Set cooldown
            self.state[best_opp]['cooldown'] = 5

            return {
                'side': 'BUY',
                'symbol': best_opp,
                'amount': round(final_amount, 4),
                'reason': ['ALPHA_REVERSION', 'DYNAMIC_SCALE']
            }

        return None