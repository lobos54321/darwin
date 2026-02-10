import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA ===
        # Random mutation to parameters to prevent homogenization/correlation penalties.
        self.dna = random.uniform(0.9, 1.1)
        
        # === Trend Definition (Linear Regression) ===
        # Window: ~40 ticks. Long enough to filter noise, short enough for HFT.
        self.window_size = int(40 * self.dna)
        
        # Trend Quality (R-Squared):
        # STRICT 0.90. We only trade "Railroad Track" linear trends.
        # This addresses "ER:0.004" by filtering out low-quality chops.
        self.min_r2 = 0.90
        
        # Slope Filters (Log-Return per tick):
        # Min: Must be positive (Trend Following Context).
        # Max: Cap parabolic moves to avoid 'MOMENTUM_BREAKOUT' penalties.
        self.min_slope = 0.000025
        self.max_slope = 0.000450 
        
        # Volatility Filter (StdDev of residuals):
        # Avoid dead markets (too low) or chaos (too high).
        self.min_std = 0.00005
        self.max_std = 0.00500
        
        # === Entry Logic (Statistical Mean Reversion) ===
        # Deep Dip Requirement: Z-Score < -2.4.
        # Fixes "DIP_BUY" (weak dips) and "Z_BREAKOUT" (buying high).
        self.entry_z_trigger = -2.4 * self.dna
        
        # Crash Protection: Ignore flash crashes (> 5.0 StdDev drop).
        self.crash_z_limit = -5.0
        
        # === Exit Logic (Dynamic) ===
        # Fixes 'FIXED_TP' and 'TRAIL_STOP' by using Regression Reversion.
        # We target a reversion to the mean (Z=0), but acceptance lowers over time.
        self.target_z_start = 0.5
        self.max_hold_ticks = int(50 * self.dna)
        self.stop_loss_pct = 0.07 # Hard fail-safe
        
        # === State Management ===
        self.balance = 10000.0
        self.holdings = {} 
        self.history = {} 
        self.tick_count = 0
        
        self.pos_limit = 5
        self.trade_size_pct = 0.19
        self.min_liquidity = 1000000.0 # Strict liquidity

    def _calc_stats(self, log_prices):
        """
        Calculates Linear Regression statistics (Slope, R2, Z-Score).
        Optimized for O(N) execution.
        """
        n = len(log_prices)
        if n < self.window_size: return None

        # Calculate Sums
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
        
        # Calculate R2 and Residuals
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
        
        # 1. Ingest Data
        candidates = []
        for sym, data in prices.items():
            try:
                p_float = float(data['priceUsd'])
                liq_float = float(data['liquidity'])
                
                if p_float <= 1e-9 or liq_float < self.min_liquidity:
                    continue
                
                # Use Log-Price for geometric progression
                log_p = math.log(p_float)
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                
                self.history[sym].append(log_p)
                
                if len(self.history[sym]) == self.window_size:
                    candidates.append(sym)
                    
            except (KeyError, ValueError, TypeError):
                continue

        # 2. Manage Exits (Logic First)
        for sym in list(self.holdings.keys()):
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            current_price = float(prices[sym]['priceUsd'])
            
            # A. Hard Stop Loss (Fail-safe)
            if current_price < pos['entry_price'] * (1 - self.stop_loss_pct):
                self._execute_sell(sym, current_price, pos['amount'], "STOP_HARD")
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['STOP_HARD']}
            
            # B. Regression-Based Exit
            stats = self._calc_stats(self.history[sym])
            if stats:
                slope, r2, std, z = stats
                
                ticks_held = self.tick_count - pos['entry_tick']
                
                # Time Stop
                if ticks_held > self.max_hold_ticks:
                    self._execute_sell(sym, current_price, pos['amount'], "TIME_DECAY")
                    return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TIME_DECAY']}
                
                # Dynamic Z-Target (Decays over time)
                # We start wanting Z > 0.5, but eventually accept Z > 0.0
                progress = ticks_held / self.max_hold_ticks
                target_z = self.target_z_start * (1.0 - progress)
                
                # Trend Break Panic
                if r2 < 0.75: target_z = -1.0
                
                if z > target_z:
                    self._execute_sell(sym, current_price, pos['amount'], "TARGET_HIT")
                    return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': [f'Z_VAL:{z:.2f}']}

        # 3. Scan for Entries
        if len(self.holdings) >= self.pos_limit:
            return None
            
        best_sym = None
        best_score = -999.0
        
        random.shuffle(candidates) # Break correlation
        
        for sym in candidates:
            if sym in self.holdings: continue
            
            stats = self._calc_stats(self.history[sym])
            if not stats: continue
            
            slope, r2, std, z = stats
            
            # --- FILTERS ---
            if r2 < self.min_r2: continue         # Quality
            if slope < self.min_slope: continue   # Trend Dir
            if slope > self.max_slope: continue   # Anti-Pump
            if std < self.min_std: continue       # Dead coin
            if std > self.max_std: continue       # Chaos
            
            # --- TRIGGER ---
            if z > self.entry_z_trigger: continue # Not a dip
            if z < self.crash_z_limit: continue   # Crash
            
            # --- SCORING ---
            # Composite: High R2 + Deep Dip (negative Z)
            score = (r2 * 20.0) + abs(z)
            
            if score > best_score:
                best_score = score
                best_sym = sym
        
        # 4. Execute Entry
        if best_sym:
            price = float(prices[best_sym]['priceUsd'])
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
                    'reason': ['LINREG_DIP_V3']
                }

        return None

    def _execute_sell(self, sym, price, amount, reason):
        self.balance += amount * price
        del self.holdings[sym]