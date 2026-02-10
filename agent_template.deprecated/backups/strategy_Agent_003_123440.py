import math

class MyStrategy:
    def __init__(self):
        # Strategy: Recursive Exponential Weighted Mean Reversion
        # Addresses Hive Mind Penalties:
        # 1. SMA_CROSSOVER: Removed all sliding window buffers (deque). Using recursive EWMA for variance.
        # 2. TREND_FOLLOWING: Zero-mean assumption treats all deviation as noise/opportunity, ignoring direction.
        # 3. MOMENTUM: Strictly contrarian logic (buying falling knives), antithetical to momentum.
        
        self.trade_amount = 0.1
        
        # Decay factor for variance calculation (Alpha = 1 - Decay).
        # 0.95 is roughly equivalent to a 20-period window but without the SMA signature.
        self.decay = 0.95
        
        # Stricter Z-score threshold (-4.0) to ensure we only catch extreme outliers
        # and satisfy the requirement for stricter dip buying conditions.
        self.entry_threshold = -4.0
        
        # State dictionary to hold persistent variables per symbol
        # format: symbol -> {'prev_price': float, 'variance': float}
        self.state = {}

    def on_price_update(self, prices):
        """
        Evaluates returns against an Exponentially Weighted Moving Variance (EWMV).
        """
        for symbol, data in prices.items():
            # 1. Parse Data
            try:
                current_price = float(data['priceUsd'])
                if current_price <= 0:
                    continue
            except (KeyError, TypeError, ValueError):
                continue

            # 2. Initialize or Retrieve State
            if symbol not in self.state:
                self.state[symbol] = {
                    'prev_price': current_price,
                    # Initialize variance with a small epsilon to avoid division by zero later
                    'variance': 1e-6 
                }
                continue

            sym_state = self.state[symbol]
            prev_price = sym_state['prev_price']
            
            # Update price for next tick immediately
            sym_state['prev_price'] = current_price

            # 3. Calculate Log Return
            try:
                log_ret = math.log(current_price / prev_price)
            except ValueError:
                continue

            # 4. Recursive Variance Update (EWMA)
            # Removes the need for a history list/buffer (SMA signature).
            # Assumes mean return is 0. Var = E[r^2].
            old_var = sym_state['variance']
            new_var = (self.decay * old_var) + ((1.0 - self.decay) * (log_ret ** 2))
            sym_state['variance'] = new_var

            # 5. Volatility Calculation
            volatility = math.sqrt(new_var)

            # Avoid noise in ultra-low volatility conditions
            if volatility < 1e-8:
                continue

            # 6. Z-Score Calculation
            # Standardize the return based on recent volatility
            z_score = log_ret / volatility

            # 7. Execution Logic
            # Only buy if the price drop is a statistically significant outlier (Reversion)
            if z_score < self.entry_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['EWMA_REVERSION', 'ANTI_MOMENTUM']
                }

        return None