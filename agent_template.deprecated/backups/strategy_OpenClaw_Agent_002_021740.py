import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18  # Allocate 18% per trade
        
        # === Asset Filters (Quality Control) ===
        # High liquidity requirements to avoid manipulation and slippage
        self.min_liquidity = 70000000.0 
        self.min_volume = 30000000.0
        
        # === Strategy Core Parameters ===
        self.lookback = 30
        
        # === Penalty Fixes & Mutations ===
        
        # Fix for 'Z:-3.93' (Catching Falling Knives):
        # We establish a Strict Band Pass for Z-Score.
        # We REJECT if Z < -2.6 (Too steep, likely a crash/breakdown)
        # We REJECT if Z > -1.5 (Not enough mean reversion potential)
        self.z_min = -2.6
        self.z_max = -1.5
        
        # Fix for 'LR_RESIDUAL' (Poor Trend Fit):
        # We enforce a very low RMSE (Root Mean Square Error).
        # This ensures price is respecting the linear trend model.
        # High RMSE indicates chaotic action which leads to unpredictable residuals.
        self.max_rmse = 0.008  # Max 0.8% deviation from trend line
        
        # Mutation: Trend Alignment
        # Instead of buying any dip, we ONLY buy dips in UPTRENDS or FLAT markets.
        # We reject negative slopes to avoid buying into a structural downtrend.
        self.min_slope = 0.00001 # Slope must be slightly positive
        
        # Secondary Filters
        self.rsi_limit = 35.0  # Deep oversold
        self.max_volatility = 0.04 # Reject if standard deviation > 4% of price (too volatile)
        
        # === Exit Logic ===
        self.stop_loss = 0.035          # 3.5% Stop
        self.roi_trail_start = 0.012    # Start trailing at 1.2% profit
        self.trail_gap = 0.006          # Tight 0.6% trail
        self.max_hold_ticks = 20        # Quick rotation
        
        # === State ===
        self.positions = {}
        self.history = {}
        self.cooldowns = {}

    def _calculate_metrics(self, prices):
        """
        Calculates Linear Regression metrics (Slope, RMSE) and Z-Score/RSI.
        """
        n = len(prices)
        if n < self.lookback: return None
        
        # 1. Normalize prices to base for Scale Invariant Regression
        base = prices[0]
        y = [p / base for p in prices]
        x = list(range(n))
        
        sx = sum(x)
        sy = sum(y)
        sxy = sum(i * j for i, j in zip(x, y))
        sxx = sum(i * i for i in x)
        
        denom = n * sxx - sx * sx
        if denom == 0: return None
        
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        
        # 2. Calculate RMSE (Residual Check)
        # We sum squared errors between Actual Normalized Price and Predicted Price
        sse = 0.0
        for i in range(n):
            pred = slope * i + intercept
            sse += (y[i] - pred) ** 2
            
        rmse = math.sqrt(sse / n)
        
        # 3. Calculate Z-Score & Volatility
        mean_price = sum(prices) / n
        variance = sum((p - mean_price) ** 2 for p in prices) / n
        std_dev = math.sqrt(variance)
        
        z_score = 0.0
        volatility = 0.0
        
        if std_dev > 0:
            z_score = (prices[-1] - mean_price) / std_dev
            volatility = std_dev / base
            
        # 4. RSI
        deltas = [prices[i] - prices[i-1] for i in range(1, n)]
        gains = sum(d for d in deltas[-14:] if d > 0)
        losses = sum(abs(d) for d in deltas[-14:] if d < 0)
        
        rsi = 100.0
        if losses > 0:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            "slope": slope,
            "rmse": rmse,
            "z_score": z_score,
            "volatility": volatility,
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
                    trail_level = pos['high'] * (1.0 - self.trail_gap)
                    if curr_price <= trail_level:
                        action = "SELL"
                        reason = "TRAIL_PROFIT"
                
                # C. Time Expiry (Rotate capital)
                elif pos['time'] >= self.max_hold_ticks:
                    if roi > -0.015: 
                        action = "SELL"
                        reason = "TIMEOUT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldowns[sym] = 30 # Longer cooldown to reset
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
            
            # Cooldown
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
                m = self._calculate_metrics(hist)
                if not m: continue
                
                # --- PENALTY FIX LOGIC ---
                
                # Z-Score Band: [-2.6, -1.5]
                # Fix 'Z:-3.93': Rejects crashes (< -2.6).
                if m['z_score'] < self.z_min: continue 
                if m['z_score'] > self.z_max: continue
                
                # RMSE Check
                # Fix 'LR_RESIDUAL': Rejects noisy assets not respecting the trend.
                if m['rmse'] > self.max_rmse: continue
                
                # Slope Check (Mutation)
                # Only buy dips in POSITIVE trends to avoid downtrend continuation.
                if m['slope'] < self.min_slope: continue
                
                # Volatility Check
                # Reject wildly volatile assets that likely have structural issues.
                if m['volatility'] > self.max_volatility: continue
                
                # RSI Check
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
            # Sort by CLEANEST FIT (Lowest RMSE) first, then RSI.
            # This prioritizes safety and predictability over raw dip depth.
            candidates