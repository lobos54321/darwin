import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18
        
        # === Asset Quality Filters ===
        self.min_liquidity = 50000000.0 
        self.min_volume = 20000000.0
        
        # === Strategy Parameters ===
        self.lookback = 30
        
        # === Z-Score Band Pass (Fix for Z:-3.93) ===
        # We strictly reject Z-scores below the floor to avoid falling knives.
        # Range: Buy between -1.95 and -2.85.
        self.z_entry_upper = -1.95
        self.z_hard_floor = -2.85 
        
        # === Linear Regression Filters (Fix for LR_RESIDUAL) ===
        # High residuals indicate the price is not following a predictable path (noisy/chaotic).
        # We also filter out slopes that are too steep (structural collapse).
        self.max_residual_std = 0.025   # Max 2.5% deviation from regression line
        self.max_down_slope = -0.004    # Reject trends steeper than -0.4% per tick
        
        # === Secondary Indicators ===
        self.rsi_period = 14
        self.rsi_limit = 35.0
        self.max_daily_drop = -12.0     # Reject > 12% drop in 24h
        
        # === Exit Logic ===
        self.stop_loss = 0.04           # 4% Stop
        self.roi_trail_start = 0.02     # Start trailing at 2% profit
        self.trail_gap = 0.01           # 1% Trail distance
        self.max_hold_ticks = 30        # Faster rotation
        
        # === State ===
        self.positions = {}     # {sym: {entry, high, amount, time}}
        self.history = {}       # {sym: deque([prices])}
        self.blacklisted = {}   # {sym: cooldown_counter}

    def _calculate_linreg_metrics(self, prices):
        """
        Calculates normalized slope and residual standard deviation.
        Normalization (p/p[0]) ensures metrics work for both BTC and shitcoins.
        """
        n = len(prices)
        if n < 2: return 0.0, 999.0
        
        # Normalize prices to start at 1.0
        y = [p / prices[0] for p in prices]
        x = list(range(n))
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_xx = sum(i * i for i in x)
        
        denom = (n * sum_xx - sum_x * sum_x)
        if denom == 0: return 0.0, 999.0
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate Residuals (Error)
        # Sum of squared differences between Actual Y and Predicted Y
        sse = sum((y[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
        residual_std = math.sqrt(sse / n)
        
        return slope, residual_std

    def _calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1: return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent = deltas[-self.rsi_period:]
        
        gains = sum(d for d in recent if d > 0)
        losses = sum(abs(d) for d in recent if d < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

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
                
                # A. Stop Loss
                if roi <= -self.stop_loss:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Trailing Profit
                elif peak_roi >= self.roi_trail_start:
                    trail_price = pos['high'] * (1.0 - self.trail_gap)
                    if curr_price <= trail_price:
                        action = "SELL"
                        reason = "TRAIL_PROFIT"
                
                # C. Time Expiry
                elif pos['time'] >= self.max_hold_ticks:
                    # Sell if not significantly underwater to free capital
                    if roi > -0.015:
                        action = "SELL"
                        reason = "TIMEOUT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.blacklisted[sym] = 15 # Cooldown
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
            except (ValueError, KeyError):
                continue

        # --- 2. Entry Logic ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions: continue
            
            # Cooldown Management
            if sym in self.blacklisted:
                self.blacklisted[sym] -= 1
                if self.blacklisted[sym] <= 0:
                    del self.blacklisted[sym]
                else:
                    continue
            
            try:
                # 2a. Liquidity & Vol Filters
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                change24h = float(data.get("priceChange24h", 0))
                
                if liq < self.min_liquidity or vol < self.min_volume: continue
                if change24h < self.max_daily_drop: continue # Avoid death spirals
                
                price = float(data["priceUsd"])
                if price <= 0: continue
                
                # 2b. History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                hist = list(self.history[sym])
                if len(hist) < self.lookback: continue
                
                # 2c. Statistical Filters (LR & Z-Score)
                slope, res_std = self._calculate_linreg_metrics(hist)
                
                # REJECT (LR_RESIDUAL Fix): If price doesn't fit the line, it's noise.
                if res_std > self.max_residual_std: continue
                
                # REJECT: If slope is too steep downwards, it's a crash, not a dip.
                if slope < self.max_down_slope: continue
                
                # Calculate Z-Score
                mean = sum(hist) / len(hist)
                variance = sum((x - mean) ** 2 for x in hist) / len(hist)
                std_dev = math.sqrt(variance)
                
                if std_dev == 0: continue
                z_score = (price - mean) / std_dev
                
                # REJECT (Z:-3.93 Fix): Strict Band Pass
                if z_score > self.z_entry_upper: continue # Not cheap enough
                if z_score < self.z_hard_floor: continue  # Too cheap (Crash)
                
                # 2d. RSI Filter
                rsi = self._calculate_rsi(hist)
                if rsi > self.rsi_limit: continue
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'z': z_score,
                    'rsi': rsi,
                    'res_std': res_std
                })
                
            except (ValueError, KeyError, ZeroDivisionError):
                continue
                
        # --- 3. Execution ---
        if candidates:
            # Sort by RSI (Lowest) instead of Z-score to find "Oversold but Stable"
            # Preferring low RSI with passing Z/LR checks is safer than chasing lowest Z
            candidates.sort(key=lambda x: x['rsi'])
            best = candidates[0]
            
            amount = (self.balance * self.trade_pct) / best['price']
            
            self.positions[best['symbol']] = {
                'entry': best['price'],
                'amount': amount,
                'high': best['price'],
                'time': 0
            }
            
            return {
                "side": "BUY",
                "symbol": best['symbol'],
                "amount": amount,
                "reason": ["LR_FIT", f"Z:{best['z']:.2f}", f"RES:{best['res_std']:.3f}"]
            }
            
        return None