import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18
        
        # === Liquidity Filters ===
        # Strict liquidity ensures we trade assets with real structural order flow
        self.min_liquidity = 90000000.0 
        self.min_volume = 45000000.0
        
        # === Strategy Core Parameters ===
        self.lookback = 45  # Sufficient window to establish statistical significance
        
        # === Structural Trend Filters (Fix DIP_BUY) ===
        # We only engage with assets demonstrating high-fidelity uptrends.
        # This replaces blind dip buying with "Regression Reversion".
        self.min_slope = 0.00002   # Threshold for positive log-slope
        self.min_r_squared = 0.72  # High correlation required (Clean trend)
        
        # === Dynamic Value Zones (Fix KELTNER/OVERSOLD) ===
        # We define a specific band of deviation.
        # Too shallow = No Edge. Too deep = Structural Break/Crash.
        # We target the "Sweet Spot" of pullback within a trend.
        self.z_entry_upper = -1.6  # Must be at least this deviated (Cheap)
        self.z_entry_lower = -2.8  # Must NOT be lower than this (Knife Catching)
        
        # === Exit Logic ===
        self.stop_loss = 0.028          # 2.8% Hard Stop
        self.take_profit_start = 0.018  # Activate trailing at 1.8%
        self.trail_gap = 0.006          # 0.6% Trailing gap
        self.max_hold_ticks = 30        # Time limit
        
        # === State ===
        self.positions = {}
        self.history = {}
        self.cooldowns = {}

    def _calculate_regression_metrics(self, prices):
        """
        Calculates Linear Regression on Log-Prices.
        Returns Slope, R^2, and Z-Score relative to the regression line.
        """
        n = len(prices)
        if n < self.lookback: return None
        
        # Use Log Prices to normalize volatility impact across price ranges
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
        # Pearson Correlation Coefficient squared
        num_r = (n * sxy - sx * sy)
        den_r = math.sqrt(denom * (n * syy - sy * sy))
        
        r_squared = 0.0
        if den_r != 0:
            r_squared = (num_r / den_r) ** 2
            
        # 3. Z-Score (Deviation from Regression Line)
        # Calculate Standard Error of the Estimate (SEE)
        # Sum of Squared Residuals
        ssr = 0.0
        # Optimization: We only need residuals for calculation, 
        # but we also need the LAST residual for the Z-score.
        for i in range(n):
            pred = slope * i + intercept
            ssr += (y[i] - pred) ** 2
            
        std_error = math.sqrt(ssr / (n - 2)) if n > 2 else 0
        
        z_score = 0.0
        if std_error > 0:
            # Current projected value (at last index)
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
                    # If we aren't clearly winning by max time, exit to free capital
                    if roi < 0.005: 
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
                m = self._calculate_regression_metrics(hist)
                if not m: continue
                
                # --- STRATEGY FILTERS ---
                
                # Filter 1: Trend Quality (Slope & Fit)
                # Asset must be in a confirmed mathematical uptrend.
                if m['slope'] < self.min_slope: continue
                if m['r_squared'] < self.min_r_squared: continue
                
                # Filter 2: Value Zone (Z-Score)
                # We buy pullbacks to the regression line (Mean Reversion within Trend).
                # We avoid "Oversold" traps by ignoring deep negative Z-scores.
                if m['z_score'] > self.z_entry_upper: continue # Not cheap enough
                if m['z_score'] < self.z_entry_lower: continue # Too deep (Risk of crash)
                
                # Filter 3: Micro-Structure Stabilization
                # Fix for 'DIP_BUY': Do not buy if price is strictly falling tick-over-tick.
                # Require the current price to be higher than the lowest of the last 3 ticks.
                # This ensures we aren't catching a pure falling knife.
                recent_window = hist[-3:]
                if len(recent_window) == 3:
                    if price <= min(recent_window[:-1]): continue
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'metrics': m
                })
                
            except (ValueError, KeyError, ZeroDivisionError):
                continue
        
        # --- 3. Execution Priority ---
        if candidates:
            # Sort by R-Squared. Higher R^2 = smoother trend = safer mean reversion.
            # We prioritize structure over depth of dip.
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
                "reason": ["REGRESSION_REV"]
            }
            
        return None