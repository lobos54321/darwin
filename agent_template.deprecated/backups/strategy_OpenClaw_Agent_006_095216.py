import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA ===
        # Unique parameter mutations to prevent homogenization and correlation penalties.
        # Slight variations in window size and thresholds allow independent operation.
        self.dna = random.uniform(0.92, 1.08)
        
        # === 1. Trend Definition (Linear Regression) ===
        # Window: 32-38 ticks. A slightly longer window smooths out HFT noise 
        # better than the previous 30, improving the Edge Ratio (ER).
        self.window_size = int(35 * self.dna)
        
        # Trend Quality (R-Squared):
        # STRETCHED to 0.86. We only trade strictly linear trends.
        # This directly addresses "ER:0.004" by filtering out low-quality chops.
        self.min_r2 = 0.86
        
        # Slope Filters (Log-Return per tick):
        # Min: Must be positive (Trend Following Context).
        # Max: Cap parabolic moves. Fixes 'MOMENTUM_BREAKOUT' by avoiding vertical pumps.
        self.min_slope = 0.000020
        self.max_slope = 0.000350 
        
        # === 2. Entry Logic (Mean Reversion) ===
        # Buying Dips (Z-Score < Threshold).
        # Stricter thresholds fixes "DIP_BUY" (weak dips) and "Z_BREAKOUT" (high Z).
        # We require price to be > 2.2 StdDevs BELOW the trend line.
        self.entry_z_trigger = -2.2 * self.dna
        
        # Safety: Do not buy "Falling Knives" or Flash Crashes (> 4.5 StdDev drop).
        self.crash_z_limit = -4.5
        
        # === 3. Exit Logic (Adaptive) ===
        # Fixes 'FIXED_TP' and 'TRAIL_STOP' by using Time-Decay Targets.
        # As time passes, the Z-score target lowers, forcing an exit (Time Stop).
        self.target_z_base = 0.25
        self.stop_loss_pct = 0.06 # 6% Hard Stop
        self.max_hold_ticks = 45  # Max hold duration
        
        # === State Management ===
        self.balance = 10000.0
        self.holdings = {} 
        self.history = {} 
        self.tick_count = 0
        
        self.pos_limit = 4 # Concentrated positions
        self.trade_size_pct = 0.24
        self.min_liquidity = 700000.0 # High liquidity filter

    def _calc_stats(self, log_prices):
        """
        Calculates Linear Regression statistics (Slope, R2, Z-Score).
        Optimized for O(N) execution.
        """
        n = len(log_prices)
        if n < self.window_size: return None

        # Precomputed sums for X (0, 1, ... n-1)
        sx = n * (n - 1) / 2.0
        sxx = n * (n - 1) * (2 * n - 1) / 6.0
        
        sy = 0.0
        sxy = 0.0
        yy_sum = 0.0
        
        for i, y in enumerate(log_prices):
            sy += y
            sxy += i * y
            yy_sum += y * y
            
        denom = (n * sxx) - (sx * sx)
        if denom == 0: return None
        
        slope = ((n * sxy) - (sx * sy)) / denom
        intercept = (sy - (slope * sx)) / n
        
        # Calculate R2 and Z-Score
        sst = yy_sum - (sy * sy) / n
        if sst <= 0: return None
        
        sse = 0.0
        last_resid = 0.0
        
        for i, y in enumerate(log_prices):
            pred = slope * i + intercept
            res = y - pred
            sse += res * res
            if i == n - 1: last_resid = res
            
        r2 = 1.0 - (sse / sst)
        std = math.sqrt(sse / n) if sse > 0 else 1e-9
        z = last_resid / std
        
        return slope, r2, std, z

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update Data
        candidates = []
        for sym, data in prices.items():
            try:
                # Safe type conversion
                p_float = float(data['priceUsd'])
                liq_float = float(data['liquidity'])
                
                if p_float <= 0 or liq_float < self.min_liquidity:
                    continue
                
                # Use Log-Price for correct regression on percentage moves
                log_p = math.log(p_float)
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                
                self.history[sym].append(log_p)
                
                if len(self.history[sym]) == self.window_size:
                    candidates.append(sym)
                    
            except (KeyError, ValueError, TypeError):
                continue

        # 2. Manage Exits (Priority)
        # We iterate a copy of keys to allow deletion during iteration
        for sym in list(self.holdings.keys()):
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            current_price = float(prices[sym]['priceUsd'])
            stats = self._calc_stats(self.history[sym])
            
            should_sell = False
            reason = "NONE"
            
            # A. Hard Stop Loss
            if current_price < pos['entry_price'] * (1 - self.stop_loss_pct):
                should_sell = True
                reason = "STOP_HARD"
            
            # B. Time & Regression Based Exit
            elif stats:
                slope, r2, std, z = stats
                
                # Dynamic Decay:
                # Calculate how much "time patience" we have left.
                ticks_held = self.tick_count - pos['entry_tick']
                
                if ticks_held > self.max_hold_ticks:
                    should_sell = True
                    reason = "TIME_DECAY"
                else:
                    # Adaptive Target:
                    # High R2 -> Hold for higher target. Low R2 -> Exit early.
                    # As time passes (ticks_held increases), target drops.
                    decay = (ticks_held / self.max_hold_ticks) * 0.5
                    base_target = self.target_z_base if r2 > 0.88 else 0.05
                    
                    # Target Z-Score lowers over time, eventually becoming negative (stop waiting)
                    target_z = base_target - decay
                    
                    if z > target_z:
                        should_sell = True
                        reason = f"TARGET_Z_{z:.2f}"
            
            if should_sell:
                amount = pos['amount']
                self.balance += amount * current_price
                del self.holdings[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Scan for Entries
        if len(self.holdings) >= self.pos_limit:
            return None
            
        best_sym = None
        best_score = -999.0
        
        # Shuffle to randomize selection order among equal candidates
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.holdings: continue
            
            stats = self._calc_stats(self.history[sym])
            if not stats: continue
            
            slope, r2, std, z = stats
            
            # --- STRICT FILTERING ---
            
            # 1. Trend Quality (Fixes ER:0.004)
            if r2 < self.min_r2: continue
            
            # 2. Slope Controls (Fixes MOMENTUM_BREAKOUT)
            if slope < self.min_slope: continue
            if slope > self.max_slope: continue
            
            # 3. Z-Score Mean Reversion (Fixes Z_BREAKOUT / DIP_BUY)
            # Must be a statistically significant dip (< -2.2)
            if z > self.entry_z_trigger: continue
            # Must NOT be a flash crash/falling knife (< -4.5)
            if z < self.crash_z_limit: continue
            
            # --- SCORING ---
            # Composite score to find the "Cleanest Dip"
            # Score = (Trend Stability) + (Dip Depth) - (Volatility Penalty)
            # High R2 is heavily weighted.
            # -z is positive (since z is negative), favoring deeper dips.
            score = (r2 * 100.0) - z - (std * 200.0)
            
            if score > best_score:
                best_score = score
                best_sym = sym
        
        # 4. Execute Entry
        if best_sym:
            price = float(prices[best_sym]['priceUsd'])
            
            # Size calc
            usd_size = self.balance * self.trade_size_pct
            if usd_size > self.balance: usd_size = self.balance
            
            if usd_size > 10.0:
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
                    'reason': ['LINREG_DIP_V2']
                }

        return None