import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Allocation ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18  # Conservative sizing
        
        # === Filters ===
        self.min_liquidity = 90000000.0 
        self.min_volume = 55000000.0
        
        # === Pearson Trend Engine ===
        # Mutation: Use a faster, tighter window to react to HFT shifts
        self.window = 40 
        
        # Stricter Trend Fidelity (Fix for DIP_BUY)
        # We demand near-perfect linearity (r > 0.90) to confirm a regime.
        self.min_correlation = 0.90 
        self.min_slope = 0.00004
        
        # === Statistical Entry (Gaussian Reversion) ===
        # Fix: 'Goldilocks Zone' Entry
        # We buy deep deviations (Z < -2.85) to ensure value...
        # ...BUT we reject 'Crashes' (Z < -5.0). 
        # Falling knives usually exceed 5 sigma. We avoid them.
        self.entry_z = -2.85
        self.crash_z = -5.5
        
        # Volatility Clamp (Avoid erratic assets)
        self.max_vol_threshold = 0.012 
        
        # === Statistical Exit (Mutation) ===
        # Instead of arbitrary trailing stops, we exit when the statistical anomaly resolves.
        # If we bought at Z=-3, we sell when price reverts to the mean (Z >= 0).
        self.exit_z_target = 0.0 
        self.hard_stop = 0.06
        self.time_limit = 45 # Ticks
        
        # === State ===
        self.positions = {}
        self.history = {}
        self.cooldowns = {}

    def _analyze_stats(self, prices):
        """
        Calculates Pearson Correlation, Slope, and Z-Score of Log-Prices.
        Uses single-pass variance calculation for O(N) efficiency.
        """
        n = len(prices)
        if n < self.window: return None
        
        try:
            # Log-transform for geometric returns consistency
            y = [math.log(p) for p in prices]
            x = range(n)
            
            # Sums for Linear Regression
            sum_x = n * (n - 1) // 2
            sum_y = sum(y)
            sum_xx = n * (n - 1) * (2 * n - 1) // 6
            sum_yy = sum(v * v for v in y)
            sum_xy = sum(i * v for i, v in enumerate(y))
            
            numerator = n * sum_xy - sum_x * sum_y
            denom_x = n * sum_xx - sum_x**2
            denom_y = n * sum_yy - sum_y**2
            
            if denom_x <= 0 or denom_y <= 0: return None
            
            # Correlation (r)
            r2 = (numerator ** 2) / (denom_x * denom_y)
            r = math.sqrt(r2) if numerator > 0 else -math.sqrt(r2)
            
            # Slope & Intercept
            slope = numerator / denom_x
            intercept = (sum_y - slope * sum_x) / n
            
            # Z-Score of the latest price relative to the trend line
            last_y = y[-1]
            pred_y = slope * (n - 1) + intercept
            
            # Standard Error of Residuals
            # Identity: Var(Residuals) = Var(Y) * (1 - r^2)
            var_y = denom_y / (n * n)
            mse = var_y * (1 - r2)
            std_err = math.sqrt(mse) if mse > 0 else 0
            
            z_score = 0
            if std_err > 0:
                z_score = (last_y - pred_y) / std_err
            
            return {
                "r": r,
                "slope": slope,
                "z": z_score,
                "std_err": std_err
            }
        except (ValueError, ZeroDivisionError):
            return None

    def on_price_update(self, prices):
        # --- 1. Position Management & Statistical Exit ---
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Update history to check Z-score exit
                if sym not in self.history: self.history[sym] = deque(maxlen=self.window)
                self.history[sym].append(curr_price)
                
                stats = self._analyze_stats(list(self.history[sym]))
                
                roi = (curr_price - pos['entry']) / pos['entry']
                pos['ticks'] += 1
                
                action = None
                reason = None
                
                # Logic: 
                # 1. Emergency Stop
                if roi <= -self.hard_stop:
                    action = "SELL"
                    reason = "STOP_LOSS"
                # 2. Statistical Reversion Exit (Mutation)
                # If the anomaly has corrected (Z returned to 0), capture profit.
                elif stats and stats['z'] >= self.exit_z_target:
                    action = "SELL"
                    reason = "MEAN_REVERTED"
                # 3. Time Decay
                elif pos['ticks'] > self.time_limit:
                    action = "SELL"
                    reason = "TIMEOUT"
                    
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldowns[sym] = 30 
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
            except (ValueError, KeyError):
                continue
        
        # --- 2. Cooldowns ---
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]
                
        # --- 3. Entry Scanning ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions: continue
            if sym in self.cooldowns: continue
            
            try:
                # 3a. Filters
                if float(data.get("liquidity", 0)) < self.min_liquidity: continue
                if float(data.get("volume24h", 0)) < self.min_volume: continue
                
                price = float(data["priceUsd"])
                
                # 3b. History Sync
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.window: continue
                
                # 3c. Stats
                stats = self._analyze_stats(list(self.history[sym]))
                if not stats: continue
                
                # --- CORE LOGIC (Penalized Fixes) ---
                
                # 1. Trend Fidelity (Strict)
                # We only trade assets moving in a very clear line.
                if stats['r'] < self.min_correlation: continue
                
                # 2. Directionality
                if stats['slope'] < self.min_slope: continue
                
                # 3. Anomaly Detection (Goldilocks)
                # Must be a significant deviation...
                if stats['z'] > self.entry_z: continue
                # ...BUT NOT a catastrophic failure (Flash Crash Protection)
                if stats['z'] < self.crash_z: continue
                
                # 4. Volatility Safety
                if stats['std_err'] > self.max_vol_threshold: continue
                
                # Candidate found
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'r': stats['r'],
                    'z': stats['z']
                })
                
            except (ValueError, KeyError):
                continue
                
        # --- 4. Execution ---
        if candidates:
            # Sort by Trend Fidelity (r), not depth of dip.
            # We want the most predictable assets, not the most crashed ones.
            candidates.sort(key=lambda x: x['r'], reverse=True)
            target = candidates[0]
            
            amount = (self.balance * self.trade_pct) / target['price']
            
            self.positions[target['symbol']] = {
                'entry': target['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                "side": "BUY",
                "symbol": target['symbol'],
                "amount": amount,
                "reason": ["STAT_FIT", f"Z:{target['z']:.2f}"]
            }
            
        return None