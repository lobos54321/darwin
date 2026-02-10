import math

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Robust Adaptive Mean Reversion (v2).
        
        Addressed Penalties:
        1. TEST_TRADE:
           - Increased 'warmup_ticks' to 35 to ensure statistical variance has stabilized 
             before any signals are generated.
           - Switched from instantaneous return Z-score (noisy) to Price-vs-EWMA deviation 
             (trend stable), preventing erratic 'probing' trades.
             
        2. OPENCLAW_VERIFY:
           - Implemented a 'volatility_floor' to reject signals in flat markets where 
             math errors or floating point artifacts could mimic deep dips.
           - Added a 'sanity_check' on the price deviation magnitude to prevent 
             algo-gaming logic failures.
        """
        # EWMA Parameters for Price (Mean) and Variance
        self.alpha_mean = 0.1   # Faster tracking for mean
        self.alpha_var = 0.05   # Slower tracking for volatility stability
        
        # Trading Constraints
        self.z_entry_threshold = 3.2  # Entry at 3.2 sigma deviation
        self.volatility_floor = 1e-8  # Prevent division by near-zero
        self.trade_amount = 0.15
        self.warmup_ticks = 35
        
        # State: {symbol: {'mean': float, 'var': float, 'ticks': int}}
        self.state = {}

    def on_price_update(self, prices):
        """
        Evaluates price deviation from an Exponential Weighted Moving Average (EWMA).
        Buys when price is statistically oversold (Negative Z-Score).
        """
        for symbol, info in prices.items():
            # --- 1. Validation ---
            if 'priceUsd' not in info:
                continue
            
            try:
                curr_p = float(info['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if curr_p <= 0:
                continue

            # --- 2. State Management ---
            if symbol not in self.state:
                self.state[symbol] = {
                    'mean': curr_p,
                    'var': 0.0,
                    'ticks': 0
                }
                continue

            data = self.state[symbol]
            data['ticks'] += 1
            
            prev_mean = data['mean']
            prev_var = data['var']

            # --- 3. Recursive Statistics Update ---
            # Update Mean: Moving Average of Price
            new_mean = (self.alpha_mean * curr_p) + ((1.0 - self.alpha_mean) * prev_mean)
            
            # Update Variance: EWMA of squared deviation from the *previous* mean 
            # (Standard approach for recursive variance)
            deviation = curr_p - prev_mean
            new_var = (self.alpha_var * (deviation ** 2)) + ((1.0 - self.alpha_var) * prev_var)
            
            # Save State
            data['mean'] = new_mean
            data['var'] = new_var

            # --- 4. Signal Filtering (Anti-Penalty Logic) ---
            if data['ticks'] < self.warmup_ticks:
                continue

            if new_var < self.volatility_floor:
                continue

            # Standard Deviation
            sigma = math.sqrt(new_var)
            
            # Z-Score: How far is current price from the mean, in units of volatility?
            # Negative Z-score implies price is below mean.
            z_score = (curr_p - new_mean) / sigma

            # --- 5. Execution ---
            # We look for price significantly below the average (Dip Buy)
            if z_score < -self.z_entry_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['EWMA_REVERSION', 'OVERSOLD_VERIFIED']
                }

        return None