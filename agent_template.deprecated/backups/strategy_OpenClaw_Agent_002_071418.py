import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18
        
        # === Liquidity Filters ===
        # Increased strictness to avoid slippage on thin books
        self.min_liquidity = 90000000.0 
        self.min_volume = 45000000.0
        
        # === Strategy Core Parameters ===
        self.lookback = 50  # Increased window for better statistical significance
        
        # === Structural Trend Filters (Fix DIP_BUY) ===
        # Stricter thresholds for trend confirmation
        self.min_slope = 0.000025   # Steepness requirement
        self.min_r_squared = 0.78   # High correlation required (Smoother trend)
        
        # === Dynamic Value Zones (Fix KELTNER/OVERSOLD) ===
        # "Regression Reversion": We target a deeper, safer pocket.
        # Shifted lower to avoid premature entry on falling knives.
        self.z_entry_upper = -1.9  # Must be significantly deviated (Cheap)
        self.z_entry_lower = -3.2  # Floor to avoid structural breaks
        
        # === Exit Logic ===
        self.stop_loss = 0.025          # 2.5% Hard Stop
        self.take_profit_start = 0.015  # Activate trailing earlier
        self.trail_gap = 0.005          # Tight 0.5% Trailing gap
        self.max_hold_ticks = 40        # Extended time limit for trend resumption
        
        # === State ===
        self.positions = {}
        self.history = {}
        self.cooldowns = {}

    def _calculate_regression_metrics(self, prices):
        """
        Calculates O(N) Linear Regression on Log-Prices.
        Returns Slope, R^2, Z-Score, and Volatility metrics.
        """
        n = len(prices)
        if n < self.lookback: return None
        
        # Log-transform prices to normalize percentage moves
        try:
            y = [math.log(p) for p in prices]
        except ValueError:
            return None
            
        x = list(range(n))
        
        sx = sum(x)
        sy = sum(y)
        sxy = sum(i * j for i, j in zip(x, y))
        sxx = sum(i * i for i in x)
        syy = sum(i * i for i in y)
        
        denom = n * sxx - sx * sx
        if denom == 0: return None
        
        # 1. Slope (Trend Direction)
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        
        # 2. R-Squared (Trend Quality)
        num_r = (n * sxy - sx * sy)
        den_r = math.sqrt(denom * (n * syy - sy * sy))
        
        r_squared = 0.0
        if den_r != 0:
            r_squared = (num_r / den_r) ** 2
            
        # 3. Z-Score & Standard Error
        ssr = 0.0
        for i in range(n):
            pred = slope * i + intercept
            ssr += (y[i] - pred) ** 2
            
        std_error = math.sqrt(ssr / (n - 2)) if n > 2 else 0
        
        z_score = 0.0
        if std_error > 0:
            current_pred = slope * (n - 1) + intercept
            current_actual = y[-1]
            z_score = (current_actual - current_pred) / std_error

        return {
            "slope": slope,
            "r_squared": r_squared,
            "z_score": z_score,
            "std_error": std_error
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
                elif peak_roi >= self.take_profit_start:
                    trail_level = pos['high'] * (1.0 - self.trail_gap)
                    if curr_price <= trail_level:
                        action = "SELL"
                        reason = "TRAIL_HIT"
                
                # Logic C: Stagnation Timeout
                elif pos['time'] >= self.max_hold_ticks:
                    # Exit if not profitable enough to justify capital lockup
                    if roi < 0.003: 
                        action = "SELL"
                        reason = "TIMEOUT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldowns[sym] = 15 # Shorter cooldown to re-enter good trends
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
                # 2a. Liquidity Filter
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
                m = self._calculate_regression_metrics(hist)
                if not m: continue
                
                # --- STRATEGY FILTERS ---
                
                # Filter 1: Trend Quality (The "Rail")
                # High R^2 ensures we aren't trading random noise.
                if m['slope'] < self.min_slope: continue
                if m['r_squared'] < self.min_r_squared: continue
                
                # Filter 2: Volatility Check (Anti-Explosion)
                # If standard error is too large, the channel is broken.
                # Threshold heuristic: error shouldn't exceed ~2.5% of log price roughly
                if m['std_error'] > 0.025: continue

                # Filter 3: Value Zone (The "Snap")
                # Deeper z-score requirements to avoid minor noise dips.
                if m['z_score'] > self.z_entry_upper: continue 
                if m['z_score'] < self.z_entry_lower: continue 
                
                # Filter 4: Momentum Confirmation (Anti-Knife)
                # Ensure we aren't buying the exact bottom tick of a crash.
                # We want to see at least one tick of stabilization or uptick.
                recent_window = hist[-3:]
                if len(recent_window) == 3:
                    # Require current price to be above the minimum of the last 3
                    # And specifically, current price > previous price (immediate green tick)
                    if price <= min(recent_window[:-1]): continue
                    if price < recent_window[-2]: continue # Strict uptick check
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'metrics': m
                })
                
            except (ValueError, KeyError, ZeroDivisionError):
                continue
        
        # --- 3. Execution Priority ---
        if candidates:
            # Sort by "Trend Fidelity" (R^2)
            # We prefer smoother trends over steeper ones for mean reversion safety.
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
                "reason": ["REGRESSION_REV", f"Z:{target['metrics']['z_score']:.2f}"]
            }
            
        return None