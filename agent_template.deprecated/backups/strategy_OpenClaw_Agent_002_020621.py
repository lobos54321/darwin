import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18
        
        # === Asset Quality Filters ===
        # Increased liquidity requirements to ensure price stability
        self.min_liquidity = 60000000.0 
        self.min_volume = 25000000.0
        
        # === Strategy Parameters ===
        self.lookback = 30
        
        # === Z-Score Band Pass (Fix for Z:-3.93) ===
        # We define a "Sweet Spot" for mean reversion.
        # Z < -2.8 is REJECTED (Falling Knife / Structural Break)
        # Z > -1.8 is REJECTED (Not enough edge)
        self.z_buy_min = -2.8
        self.z_buy_max = -1.8
        
        # === Linear Regression Filters (Fix for LR_RESIDUAL) ===
        # Stricter RMSE threshold. We only want assets respecting the trend line.
        # Slope check ensures we don't buy into a vertical collapse.
        self.max_rmse = 0.015      # Max 1.5% deviation from regression line
        self.min_slope = -0.003    # Reject trends steeper than -0.3% per tick
        
        # === Secondary Indicators ===
        self.rsi_period = 14
        self.rsi_limit = 32.0      # Stricter RSI (Deep oversold only)
        self.max_daily_drop = -10.0 # Reject > 10% drop in 24h
        
        # === Exit Logic ===
        self.stop_loss = 0.035          # 3.5% Stop
        self.roi_trail_start = 0.015    # Start trailing at 1.5% profit
        self.trail_gap = 0.008          # 0.8% Trail distance
        self.max_hold_ticks = 25        # Faster rotation to free capital
        
        # === State ===
        self.positions = {}     # {sym: {entry, high, amount, time}}
        self.history = {}       # {sym: deque([prices])}
        self.cooldowns = {}     # {sym: cooldown_counter}

    def _calculate_metrics(self, prices):
        """
        Calculates Linear Regression RMSE, Slope, Z-Score, and RSI.
        """
        n = len(prices)
        if n < self.lookback: return None
        
        # 1. Normalize prices for Linear Regression (Scale Invariant)
        base_price = prices[0]
        norm_y = [p / base_price for p in prices]
        x = list(range(n))
        
        sum_x = sum(x)
        sum_y = sum(norm_y)
        sum_xy = sum(i * j for i, j in zip(x, norm_y))
        sum_xx = sum(i * i for i in x)
        
        denom = (n * sum_xx - sum_x * sum_x)
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate RMSE (Residual Error)
        sse = sum((norm_y[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
        rmse = math.sqrt(sse / n)
        
        # 2. Calculate Z-Score (on raw prices)
        mean = sum(prices) / n
        variance = sum((p - mean) ** 2 for p in prices) / n
        std_dev = math.sqrt(variance)
        
        z_score = 0.0
        if std_dev > 0:
            z_score = (prices[-1] - mean) / std_dev
            
        # 3. Calculate RSI
        deltas = [prices[i] - prices[i-1] for i in range(1, n)]
        recent = deltas[-self.rsi_period:]
        gains = sum(d for d in recent if d > 0)
        losses = sum(abs(d) for d in recent if d < 0)
        
        if losses == 0: 
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            "slope": slope,
            "rmse": rmse,
            "z_score": z_score,
            "rsi": rsi
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
                    # Sell if stagnant or small loss to rotate capital
                    if roi > -0.02: 
                        action = "SELL"
                        reason = "TIMEOUT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldowns[sym] = 20 # Cooldown to prevent re-entry
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
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]
                else:
                    continue
            
            try:
                # 2a. Liquidity & Vol Filters
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                change24h = float(data.get("priceChange24h", 0))
                
                if liq < self.min_liquidity or vol < self.min_volume: continue
                if change24h < self.max_daily_drop: continue 
                
                price = float(data["priceUsd"])
                if price <= 0: continue
                
                # 2b. History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                hist = list(self.history[sym])
                if len(hist) < self.lookback: continue
                
                # 2c. Statistical Filters
                m = self._calculate_metrics(hist)
                if not m: continue
                
                # --- PENALTY FIXES ---
                
                # Fix LR_RESIDUAL: Reject if price action is chaotic (high RMSE)
                if m['rmse'] > self.max_rmse: continue
                
                # Fix Z:-3.93: Strict Band Pass Filter
                # We REJECT if z < -2.8 to avoid catching falling knives (The specific penalty zone)
                # We REJECT if z > -1.8 to ensure we are actually buying a dip
                if m['z_score'] < self.z_buy_min: continue
                if m['z_score'] > self.z_buy_max: continue
                
                # Trend Slope Check: Avoid entering into a steep crash
                if m['slope'] < self.min_slope: continue
                
                # RSI Filter
                if m['rsi'] > self.rsi_limit: continue
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'metrics': m
                })
                
            except (ValueError, KeyError, ZeroDivisionError):
                continue
                
        # --- 3. Execution ---
        if candidates:
            # Sorting Mutation:
            # Instead of purely lowest Z-score (which risks catching knives),
            # we prioritize the "Cleanest Fit" (Lowest RMSE) combined with low RSI.
            # This finds assets that are oversold but behaving predictably.
            candidates.sort(key=lambda x: (x['metrics']['rmse'], x['metrics']['rsi']))
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
                "reason": [
                    f"Z:{best['metrics']['z_score']:.2f}", 
                    f"RMSE:{best['metrics']['rmse']:.4f}"
                ]
            }
            
        return None