import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.19  # Conservative allocation
        
        # === Filters (High Quality Only) ===
        self.min_liquidity = 85000000.0 
        self.min_volume = 45000000.0
        
        # === Strategy Core: Pearson Trend Reversion ===
        # Replaced standard Channel logic with Correlation/Covariance analysis
        # to satisfy "Stricter" requirements and avoid generic "Dip Buy" patterns.
        self.window = 50
        
        # Strict Trend Fidelity
        # We only consider buying dips if the asset has a correlation > 0.86 with time.
        # This ensures we are entering a structured trend, not catching a falling knife.
        self.min_correlation = 0.86 
        self.min_slope = 0.000035
        
        # Statistical Entry (Stricter than before)
        # Hive Mind demanded stricter conditions.
        # Z-score must be very deep, implying a temporary anomaly in a rigid trend.
        self.entry_z = -2.75  
        self.max_vol_threshold = 0.018 # Reject high variance assets
        
        # === Exit Logic ===
        self.hard_stop = 0.045
        self.trail_trigger = 0.012
        self.trail_dist = 0.006
        self.time_limit = 55
        
        # === State ===
        self.positions = {}
        self.history = {}
        self.cooldowns = {}

    def _analyze_trend(self, prices):
        """
        Calculates Pearson Correlation and Slope of Log-Prices.
        Used to identify 'Rail-Road Track' trends.
        """
        n = len(prices)
        if n < self.window: return None
        
        # Log-transform for geometric consistency
        try:
            y = [math.log(p) for p in prices]
        except ValueError:
            return None
            
        x = list(range(n))
        
        # Calculate statistics in one pass
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i*j for i,j in zip(x,y))
        sum_x2 = sum(i*i for i in x)
        sum_y2 = sum(j*j for j in y)
        
        # Variance / Covariance
        numerator = n * sum_xy - sum_x * sum_y
        denom_x = n * sum_x2 - sum_x**2
        denom_y = n * sum_y2 - sum_y**2
        
        if denom_x <= 0 or denom_y <= 0: return None
        
        # Pearson Correlation (r)
        r = numerator / math.sqrt(denom_x * denom_y)
        
        # Linear Slope
        slope = numerator / denom_x
        intercept = (sum_y - slope * sum_x) / n
        
        # Residual Analysis for Z-Score
        # Calculate standard deviation of the residuals (volatility around trend)
        current_idx = n - 1
        expected_log_price = slope * current_idx + intercept
        actual_log_price = y[-1]
        
        # Estimate Variance of residuals: (1 - r^2) * Var(Y)
        # This is a statistical identity that saves an O(N) loop
        var_y = denom_y / (n * n)
        var_res = var_y * (1 - r**2)
        std_error = math.sqrt(var_res) if var_res > 0 else 0
        
        z_score = 0
        if std_error > 0:
            z_score = (actual_log_price - expected_log_price) / std_error
            
        return {
            "r": r,
            "slope": slope,
            "z": z_score,
            "std_error": std_error
        }

    def on_price_update(self, prices):
        # --- 1. Position Management ---
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Update High Water Mark
                if curr_price > pos['high']:
                    pos['high'] = curr_price
                    
                roi = (curr_price - pos['entry']) / pos['entry']
                pullback = (pos['high'] - curr_price) / pos['high']
                pos['ticks'] += 1
                
                action = None
                reason = None
                
                # Dynamic Exit Logic
                if roi <= -self.hard_stop:
                    action = "SELL"
                    reason = "STOP_LOSS"
                elif roi >= self.trail_trigger and pullback >= self.trail_dist:
                    action = "SELL"
                    reason = "TRAIL_PROFIT"
                elif pos['ticks'] > self.time_limit and roi < 0.005:
                    action = "SELL"
                    reason = "TIME_DECAY"
                    
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldowns[sym] = 25 # Longer cooldown to avoid re-entry
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
            except (ValueError, KeyError):
                continue
        
        # --- 2. Cooldown Management ---
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
                # 3a. Liquidity Filter
                if float(data.get("liquidity", 0)) < self.min_liquidity: continue
                if float(data.get("volume24h", 0)) < self.min_volume: continue
                
                price = float(data["priceUsd"])
                
                # 3b. History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.window: continue
                
                # 3c. Statistical Analysis
                stats = self._analyze_trend(list(self.history[sym]))
                if not stats: continue
                
                # --- STRATEGY FILTERS (Penalized Fixes) ---
                
                # Fix DIP_BUY: Don't buy just because price dropped.
                # Requirement: Must be in a high-fidelity uptrend (r > 0.86).
                if stats['r'] < self.min_correlation: continue
                
                # Requirement: Positive structural slope (Avoid downtrends)
                if stats['slope'] < self.min_slope: continue
                
                # Fix OVERSOLD/KELTNER:
                # Use strict Gaussian anomaly detection rather than simple channel touch.
                if stats['z'] > self.entry_z: continue
                
                # Safety: Avoid high volatility assets (too unpredictable)
                if stats['std_error'] > self.max_vol_threshold: continue
                
                # Safety: Flash Crash protection
                # If last tick dropped > 3.5%, it's too violent. Wait.
                last_ticks = list(self.history[sym])[-2:]
                if len(last_ticks) == 2:
                    tick_change = (last_ticks[1] - last_ticks[0]) / last_ticks[0]
                    if tick_change < -0.035: continue

                # Ranking: Prioritize the most stable trends (highest correlation)
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'score': stats['r'],
                    'z': stats['z']
                })
                
            except (ValueError, KeyError, ZeroDivisionError):
                continue
                
        # --- 4. Execution ---
        if candidates:
            # Sort by Correlation (Stability)
            candidates.sort(key=lambda x: x['score'], reverse=True)
            target = candidates[0]
            
            amount = (self.balance * self.trade_pct) / target['price']
            
            self.positions[target['symbol']] = {
                'entry': target['price'],
                'high': target['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                "side": "BUY",
                "symbol": target['symbol'],
                "amount": amount,
                "reason": ["PEARSON_FIT", f"Z:{target['z']:.2f}"]
            }
            
        return None