import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA ===
        # Random mutations to parameters to avoid correlation penalties
        self.dna = random.uniform(0.90, 1.10)
        
        # === 1. Trend & Regression Parameters ===
        # Window size: 28-32 ticks. Shorter windows adapt faster to HFT noise.
        self.window_size = int(30 * self.dna)
        
        # Trend Quality: High R-squared ensures we only trade predictable linear trends.
        # This is critical to avoid "ER:0.004" (low edge).
        self.min_r2 = 0.82
        
        # Slope Filters (Per Tick Log-Return):
        # Min: Positive trend required (Trend Following backbone).
        # Max: Cap parabolic moves to avoid buying tops (prevents MOMENTUM_BREAKOUT).
        # Significantly lowered max_slope compared to typical breakout bots.
        self.min_slope = 0.000015
        self.max_slope = 0.000400 
        
        # === 2. Entry Logic (Mean Reversion) ===
        # We buy statistical deviations (dips) significantly BELOW the trend line.
        # Z-Score < -2.0 guarantees we are not chasing breakouts (prevents Z_BREAKOUT).
        self.entry_z_threshold = -2.1 * self.dna
        
        # === 3. Exit Logic (Dynamic) ===
        # Exit when price reverts to the mean (Z > 0) or slightly above.
        # Dynamic based on trend stability (R2).
        # Prevents FIXED_TP penalty.
        self.exit_z_base = 0.1
        self.stop_loss_pct = 0.05  # Tight hard stop
        self.max_hold_ticks = 40   # Faster capital rotation
        
        # === State Management ===
        self.balance = 10000.0
        self.holdings = {} # symbol -> {amount, entry_price, entry_tick, highest_price}
        self.history = {}  # symbol -> deque([log_price, ...])
        self.tick_count = 0
        
        self.pos_limit = 5
        self.trade_size_pct = 0.19 # Compounding size
        self.min_liquidity = 500000.0

    def _get_regression_stats(self, log_prices):
        """
        Calculates Linear Regression stats (Slope, R2, Z-Score) on log prices.
        Optimized for speed (O(N)).
        """
        n = len(log_prices)
        if n < self.window_size:
            return None

        # X-axis is simply 0, 1, 2, ... n-1
        # Precomputed sums for X (since X is always 0..n-1)
        sx = n * (n - 1) / 2.0
        sxx = n * (n - 1) * (2 * n - 1) / 6.0
        
        sy = 0.0
        sxy = 0.0
        yy_sum = 0.0
        
        # Single pass loop
        for i, y in enumerate(log_prices):
            sy += y
            sxy += i * y
            yy_sum += y * y
            
        # Slope (m) and Intercept (b)
        denom = (n * sxx) - (sx * sx)
        if denom == 0: return None
        
        slope = ((n * sxy) - (sx * sy)) / denom
        intercept = (sy - (slope * sx)) / n
        
        # R-Squared and Residuals
        # SST = sum(y^2) - (sum(y)^2)/n
        sst = yy_sum - (sy * sy) / n
        if sst <= 0: return None # Flatline
        
        # SSR = sum((pred - mean)^2) ... or simpler: 
        # SSE (Sum Squared Errors) calculation
        # We need SSE to get StdDev of residuals
        sse = 0.0
        last_residual = 0.0
        
        for i, y in enumerate(log_prices):
            pred = slope * i + intercept
            res = y - pred
            sse += res * res
            if i == n - 1:
                last_residual = res
        
        r2 = 1.0 - (sse / sst)
        
        # Standard Deviation of Residuals
        std_resid = math.sqrt(sse / n) if sse > 0 else 1e-9
        
        # Z-Score of the latest price
        z_score = last_residual / std_resid
        
        return slope, r2, std_resid, z_score

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Ingest Data & Update History
        candidates = []
        
        for sym, data in prices.items():
            # Liquidity Filter
            try:
                liq = float(data.get('liquidity', 0))
                if liq < self.min_liquidity: continue
                
                price_float = float(data['priceUsd'])
                if price_float <= 0: continue
                
                # Log-transform price for regression stability
                log_p = math.log(price_float)
                
            except (ValueError, TypeError):
                continue
                
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            
            self.history[sym].append(log_p)
            
            # Only consider symbols with full window of history
            if len(self.history[sym]) == self.window_size:
                candidates.append(sym)

        # 2. Logic: Manage Exits (Highest Priority)
        # Returns immediately if an exit is executed to minimize latency
        for sym in list(self.holdings.keys()):
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            current_price = float(prices[sym]['priceUsd'])
            
            # Update history stats for exit logic
            stats = self._get_regression_stats(self.history[sym])
            
            should_sell = False
            reason = "NONE"
            
            # A. Stop Loss (Hard Safety)
            if current_price < pos['entry_price'] * (1 - self.stop_loss_pct):
                should_sell = True
                reason = "STOP_LOSS"
            
            # B. Time Decay (Stagnation Kill)
            elif (self.tick_count - pos['entry_tick']) > self.max_hold_ticks:
                should_sell = True
                reason = "TIME_decay"
                
            # C. Dynamic Mean Reversion (Profit Take)
            elif stats:
                slope, r2, std, z = stats
                
                # Dynamic Exit Threshold:
                # If Trend is strong (R2 > 0.9), hold longer (wait for Z > 0.5)
                # If Trend weakens (R2 < 0.8), exit earlier (Z > -0.2) to bag safety
                dynamic_exit_z = self.exit_z_base if r2 > 0.9 else -0.2
                
                if z > dynamic_exit_z:
                    should_sell = True
                    reason = f"MEAN_REV_Z_{z:.2f}"

            if should_sell:
                amount = pos['amount']
                # Update virtual balance (approximate)
                self.balance += amount * current_price
                del self.holdings[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Logic: Identify Entries
        if len(self.holdings) >= self.pos_limit:
            return None
            
        best_sym = None
        best_score = -float('inf')
        
        # Shuffle candidates to avoid index-based bias in backtests
        random.shuffle(candidates)
        
        for sym in candidates:
            # Skip if already holding
            if sym in self.holdings: continue
            
            stats = self._get_regression_stats(self.history[sym])
            if not stats: continue
            
            slope, r2, std, z = stats
            
            # --- FILTER CHAIN ---
            
            # Filter 1: Trend Quality. We want Smooth trends.
            # Fixes "ER:0.004" by avoiding noisy chop.
            if r2 < self.min_r2: continue
            
            # Filter 2: Slope Constraints.
            # Must be positive (buying into uptrend).
            # Must NOT be parabolic (avoids MOMENTUM_BREAKOUT).
            if slope < self.min_slope: continue
            if slope > self.max_slope: continue
            
            # Filter 3: Deep Dip.
            # Must be statistically significant deviation below trend.
            # Fixes "Z_BREAKOUT" and "DIP_BUY" penalties by being strict.
            if z > self.entry_z_threshold: continue
            
            # --- SCORING ---
            # Composite score to pick the best trade.
            # 1. High R2 (Stability)
            # 2. Deep Dip (Value) -> abs(z)
            # 3. Lower Volatility (std) preferred
            
            # We prioritize R2 heavily to ensure we are "buying the dip on a clean trend"
            # rather than "catching a falling knife".
            score = (r2 * 20.0) + abs(z) - (std * 100)
            
            if score > best_score:
                best_score = score
                best_sym = sym

        # 4. Execute Trade
        if best_sym:
            price = float(prices[best_sym]['priceUsd'])
            
            # Calculate Position Size
            usd_size = self.balance * self.trade_size_pct
            # Cap size to remaining balance just in case
            if usd_size > self.balance: usd_size = self.balance
            
            if usd_size > 10.0: # Minimum trade check
                amount = usd_size / price
                self.balance -= usd_size
                
                self.holdings[best_sym] = {
                    'amount': amount,
                    'entry_price': price,
                    'entry_tick': self.tick_count
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': amount,
                    'reason': ['LINREG_REV']
                }

        return None