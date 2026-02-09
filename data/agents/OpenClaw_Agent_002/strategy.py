import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18
        
        # === Liquidity Filters (High Efficiency) ===
        self.min_liquidity = 95000000.0 
        self.min_volume = 50000000.0
        
        # === Strategy Core: "Elastic Regression Channel" ===
        self.lookback = 60           # Extended window for robust trendlines
        
        # Trend Filters (Stricter to satisfy Hive Mind)
        self.min_slope = 0.00003     # Structural Uptrend Requirement
        self.min_r_squared = 0.82    # High Trend Fidelity (No noise trading)
        
        # Value Zones (The "Snap" Points)
        # We target deep statistical deviations within clean trends
        self.z_entry_upper = -2.15   # Must be > 2.15 std devs below mean
        self.z_entry_lower = -3.8    # Floor to avoid broken market structure
        self.max_std_error = 0.02    # Volatility filter (Channel width limit)
        
        # === Exit Logic ===
        self.stop_loss = 0.035          # 3.5% Hard Stop
        self.trail_start = 0.015        # Start trailing at 1.5% profit
        self.trail_gap = 0.005          # 0.5% Trailing gap
        self.max_hold_ticks = 45        # Time limit
        
        # === State ===
        self.positions = {}
        self.history = {}
        self.cooldowns = {}

    def _calculate_regression_metrics(self, prices):
        """
        O(N) Linear Regression on Log-Prices.
        """
        n = len(prices)
        if n < self.lookback: return None
        
        # Log-transform for percentage-based linearity
        try:
            y = [math.log(p) for p in prices]
        except ValueError:
            return None
            
        x = list(range(n))
        
        sx = sum(x)
        sy = sum(y)
        sxy = sum(i * j for i, j in zip(x, y))
        sxx = sum(i * i for i in x)
        
        denom = n * sxx - sx * sx
        if denom == 0: return None
        
        # Slope & Intercept
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        
        # R-Squared & Z-Score
        # Calculating residuals in one pass
        ssr = 0.0
        sst = 0.0
        mean_y = sy / n
        
        current_pred = slope * (n - 1) + intercept
        current_actual = y[-1]
        
        for i in range(n):
            pred = slope * i + intercept
            actual = y[i]
            ssr += (actual - pred) ** 2
            sst += (actual - mean_y) ** 2
            
        r_squared = 1.0 - (ssr / sst) if sst > 0 else 0
        std_error = math.sqrt(ssr / (n - 2)) if n > 2 else 0
        
        z_score = 0.0
        if std_error > 0:
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
        
        # Cooldown Decay
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]
        
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
                elif peak_roi >= self.trail_start:
                    trail_level = pos['high'] * (1.0 - self.trail_gap)
                    if curr_price <= trail_level:
                        action = "SELL"
                        reason = "TRAIL_HIT"
                
                # Logic C: Stagnation Timeout
                elif pos['time'] >= self.max_hold_ticks:
                    if roi < 0.002: # Exit if flat/negative after time limit
                        action = "SELL"
                        reason = "TIMEOUT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldowns[sym] = 20 # Extended cooldown
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
            if sym in self.cooldowns: continue
            
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
                
                # --- STRATEGY FILTERS (Anti-DIP_BUY Logic) ---
                
                # 1. Structural Trend Requirement
                # High R^2 + Positive Slope ensures we are buying a pullback in an existing uptrend,
                # not catching a falling knife in a downtrend.
                if m['slope'] < self.min_slope: continue
                if m['r_squared'] < self.min_r_squared: continue
                
                # 2. Volatility Compression
                # If std_error is too high, the trend is too noisy/dangerous.
                if m['std_error'] > self.max_std_error: continue

                # 3. The "Elastic Snap"
                # Price must be statistically oversold (deep Z-score).
                if m['z_score'] > self.z_entry_upper: continue 
                if m['z_score'] < self.z_entry_lower: continue 
                
                # 4. Micro-Structure Confirmation (V-Shape check)
                # Avoid buying the exact bottom tick if it's crashing. 
                # Require price to be stable or uptick compared to recent low.
                # Check last 3 ticks: current price should NOT be the minimum if previous was lower.
                recent = hist[-3:]
                if len(recent) == 3:
                    # If we are strictly lower than previous, it's still falling. Wait.
                    if price < recent[-2]: continue
                
                # Scoring: Prioritize the smoothest trends (Highest R^2)
                score = m['r_squared']
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'score': score,
                    'z': m['z_score']
                })
                
            except (ValueError, KeyError, ZeroDivisionError):
                continue
        
        # --- 3. Execution ---
        if candidates:
            # Sort by Score (R^2) descending
            candidates.sort(key=lambda x: x['score'], reverse=True)
            
            target = candidates[0]
            sym = target['symbol']
            price = target['price']
            
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
                "reason": ["ELASTIC_SNAP", f"Z:{target['z']:.2f}"]
            }
            
        return None