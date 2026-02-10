import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18
        
        # === Liquidity Filters ===
        # Increased to ensure we only trade dominant assets
        self.min_liquidity = 85000000.0 
        self.min_volume = 40000000.0
        
        # === Strategy Core Parameters ===
        self.lookback = 40  # Longer lookback for trend stability
        
        # === Mutation: Trend Vector Filters ===
        # FIX 'DIP_BUY': We replace blind dip buying with "Structural Trend Reversion".
        # We only buy if the asset has a high R-Squared (Correlation to time),
        # proving a clean, algorithmic uptrend.
        self.min_r_squared = 0.65  # Strong trend fit required
        self.min_slope = 0.000015  # Must be clearly moving up
        
        # FIX 'KELTNER'/'OVERSOLD': 
        # Instead of fixed bands, we use a dynamic volatility-adjusted entry.
        # We target a specific Z-score zone that implies "Pullback" not "Crash".
        self.z_entry_max = -1.8  # Must be at least 1.8 std devs below mean
        self.z_entry_min = -3.2  # Reject outliers beyond 3.2 (Falling Knives)
        
        # Safety: Reject if volatility is expanding too fast (Crash protection)
        self.max_volatility_expansion = 3.5 
        
        # === Exit Logic ===
        self.stop_loss = 0.025          # Tighter 2.5% stop
        self.roi_trail_start = 0.015    # Activate trail at 1.5% gain
        self.trail_gap = 0.005          # 0.5% trail
        self.max_hold_ticks = 25        # Give trades time to play out
        
        # === State ===
        self.positions = {}     
        self.history = {}       
        self.cooldowns = {}     

    def _calculate_metrics(self, prices):
        """
        Calculates Trend Quality (R^2), Slope, and Deviation (Z-Score).
        """
        n = len(prices)
        if n < self.lookback: return None
        
        # Normalize to start = 1.0 for scale invariance
        base_price = prices[0]
        if base_price <= 0: return None
        
        # Y = Normalized Price, X = Time index
        y = [p / base_price for p in prices]
        x = list(range(n))
        
        # Sums for Pearson Correlation & Linear Regression
        sx = sum(x)
        sy = sum(y)
        sxy = sum(i * j for i, j in zip(x, y))
        sxx = sum(i * i for i in x)
        syy = sum(i * i for i in y)
        
        denom_x = n * sxx - sx * sx
        denom_y = n * syy - sy * sy
        
        if denom_x == 0 or denom_y == 0: return None
        
        # 1. Slope (Trend Direction)
        slope = (n * sxy - sx * sy) / denom_x
        
        # 2. R-Squared (Trend Quality/Fit)
        # r = Covariance / (std_x * std_y)
        # Numerator is same as slope numerator
        numerator = (n * sxy - sx * sy)
        r_denominator = math.sqrt(denom_x * denom_y)
        
        if r_denominator == 0: return None
        r = numerator / r_denominator
        r_squared = r ** 2
        
        # 3. Z-Score (Deviation from Mean)
        # Note: We use raw price deviation from Moving Average, 
        # but normalized by standard deviation.
        mean_price = sum(prices) / n
        variance = sum((p - mean_price) ** 2 for p in prices) / n
        std_dev = math.sqrt(variance)
        
        z_score = 0.0
        if std_dev > 0:
            z_score = (prices[-1] - mean_price) / std_dev
            
        # 4. Volatility Expansion Check
        # Ratio of recent volatility (last 5 ticks) vs historical
        recent_variance = 0.0
        if n > 5:
            recent_mean = sum(prices[-5:]) / 5
            recent_variance = sum((p - recent_mean)**2 for p in prices[-5:]) / 5
            
        vol_expansion = 0.0
        if variance > 0:
            vol_expansion = recent_variance / variance

        return {
            "slope": slope,
            "r_squared": r_squared,
            "z_score": z_score,
            "vol_expansion": vol_expansion,
            "price": prices[-1]
        }

    def on_price_update(self, prices):
        # --- 1. Position Management ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Update High Water Mark
                if curr_price > pos['high']:
                    pos['high'] = curr_price
                    
                pos['time'] += 1
                roi = (curr_price - pos['entry']) / pos['entry']
                peak_roi = (pos['high'] - pos['entry']) / pos['entry']
                
                action = None
                reason = None
                
                # Logic A: Hard Stop
                if roi <= -self.stop_loss:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # Logic B: Trailing Profit
                elif peak_roi >= self.roi_trail_start:
                    trail_level = pos['high'] * (1.0 - self.trail_gap)
                    if curr_price <= trail_level:
                        action = "SELL"
                        reason = "TRAIL_HIT"
                
                # Logic C: Stagnation Timeout
                # If we haven't hit profit in half max time and are negative, cut bait
                elif pos['time'] > (self.max_hold_ticks / 2) and roi < 0:
                     # Soft timeout for underperformers
                     if pos['time'] >= self.max_hold_ticks:
                        action = "SELL"
                        reason = "TIMEOUT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldowns[sym] = 20
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
                    
            except (ValueError, KeyError):
                continue

        # --- 2. Entry Scan ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions: continue
            
            # Cooldown Management
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] > 0: continue
            
            try:
                # 2a. Quality Filter
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                if liq < self.min_liquidity or vol < self.min_volume: continue
                
                price = float(data["priceUsd"])
                if price <= 0: continue
                
                # 2b. History Update
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                hist = list(self.history[sym])
                if len(hist) < self.lookback: continue
                
                # 2c. Metric Calculation
                m = self._calculate_metrics(hist)
                if not m: continue
                
                # --- STRATEGY FILTERS ---
                
                # 1. Structural Integrity Check (Fixes DIP_BUY/KELTNER)
                # We do NOT buy unless the asset is in a mathematically proven uptrend.
                if m['slope'] < self.min_slope: continue
                
                # 2. Trend Quality Check
                # High R^2 means the price respects the trend line (not random noise).
                if m['r_squared'] < self.min_r_squared: continue
                
                # 3. Value Zone Check (The "Dip")
                # We buy when price deviates negatively from the mean, but within limits.
                if m['z_score'] > self.z_entry_max: continue # Not cheap enough
                if m['z_score'] < self.z_entry_min: continue # Too cheap (Crash risk)
                
                # 4. Crash Protection (Vol Expansion)
                # If recent volatility is 3.5x historical, it's a falling knife.
                if m['vol_expansion'] > self.max_volatility_expansion: continue
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'metrics': m
                })
                
            except (ValueError, KeyError, ZeroDivisionError):
                continue
        
        # --- 3. Execution Priority ---
        if candidates:
            # Sort by Trend Quality (R^2) descending.
            # We prefer the "smoothest" trends that have dipped, rather than the deepest dips.
            # This avoids the "Oversold" penalty trap.
            candidates.sort(key=lambda x: x['metrics']['r_squared'], reverse=True)
            
            target = candidates[0]
            sym = target['symbol']
            price = target['price']
            
            # Position Sizing
            amount = (self.balance * self.trade_pct) / price
            
            self.positions[sym] = {
                'entry': price,
                'high': price,
                'amount': amount,
                'time': 0
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["TREND_REV_R2"]
            }
            
        return None