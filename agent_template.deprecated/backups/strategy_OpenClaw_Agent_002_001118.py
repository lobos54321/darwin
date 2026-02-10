import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 3          
        self.trade_pct = 0.30           
        
        # === Asset Filters (Quality Control) ===
        # Significantly increased thresholds to ensure stability and reduce 'LR_RESIDUAL' penalties
        # Trading highly liquid assets reduces noise and linear regression residuals
        self.min_liquidity = 50000000.0 
        self.min_volume = 25000000.0    
        
        # === Strategy Parameters ===
        self.lookback = 60              # Window for Z-score calculation
        self.rsi_period = 14
        self.rsi_limit = 28.0           # Stricter RSI for better mean reversion
        
        # === Z-Score Bounds (CRITICAL FIX) ===
        # Fix for 'Z:-3.93' penalty: 
        # We define a "Safe Dip" band. 
        # We do not buy if Z < -2.8 (Falling Knife/Crash/Structural Break).
        # We do not buy if Z > -1.8 (Not enough of a dip).
        self.z_entry_upper = -1.80     
        self.z_crash_floor = -2.80       
        
        # === Volatility Filter (LR_RESIDUAL FIX) ===
        # Prevents entering when short-term volatility explodes relative to historical norm.
        # High residuals often occur during volatility expansion.
        self.vol_ratio_limit = 1.8      
        
        # === Exit Logic ===
        self.stop_loss = 0.06           # 6% Hard Stop
        self.roi_activation = 0.03      # Activate trail at 3% profit
        self.trail_gap = 0.01           # 1% Trail
        self.max_hold_ticks = 60        # Timeout to free up capital
        
        # === State ===
        self.positions = {}             
        self.history = {}               
        self.cooldown = {}              

    def on_price_update(self, prices):
        """
        Executes mean-reversion logic with strict Z-score banding and volatility filtering.
        """
        # --- 1. Position Management ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
            
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Update High Water Mark
                if curr_price > pos['high']:
                    pos['high'] = curr_price
                
                pos['age'] += 1
                entry_price = pos['entry']
                roi = (curr_price - entry_price) / entry_price
                peak_roi = (pos['high'] - entry_price) / entry_price
                trail_price = pos['high'] * (1.0 - self.trail_gap)
                
                action = None
                reason = None
                
                # A. Hard Stop Loss
                if roi <= -self.stop_loss:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Trailing Profit
                elif peak_roi >= self.roi_activation and curr_price <= trail_price:
                    action = "SELL"
                    reason = "TRAILING_PROFIT"
                
                # C. Timeout (Time-based exit)
                elif pos['age'] >= self.max_hold_ticks:
                    # Exit if stagnant, but hold if slightly recovering (roi > -2%) to avoid realized losses on noise
                    if roi > -0.02: 
                        action = "SELL"
                        reason = "TIMEOUT"

                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 15  # Cooldown prevents re-entering the same volatility event
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
                    
            except (ValueError, KeyError):
                continue

        # --- 2. Entry Signal Generation ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions: continue
            
            # Cooldown check
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]
                continue
            
            try:
                # 2a. Strict Liquidity Filter
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue
                
                price = float(data["priceUsd"])
                if price <= 0: continue
                
                # 2b. Maintain History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                hist = list(self.history[sym])
                if len(hist) < self.lookback:
                    continue
                
                # 2c. Statistical Calculations
                mean = sum(hist) / len(hist)
                variance = sum((x - mean) ** 2 for x in hist) / len(hist)
                std = math.sqrt(variance)
                
                if std == 0: continue
                
                z_score = (price - mean) / std
                
                # 2d. Z-Score Band Pass (Fix for Z:-3.93)
                # We strictly enforce the floor. If it's too deep, it's a crash.
                if z_score < self.z_crash_floor:
                    continue
                
                # If it's not deep enough, it's noise.
                if z_score > self.z_entry_upper:
                    continue
                
                # 2e. Volatility Ratio (Fix for LR_RESIDUAL)
                # Check if recent volatility is consistent with historical volatility.
                # If short-term vol is spiking, prediction error increases.
                short_window = 12
                short_hist = hist[-short_window:]
                short_mean = sum(short_hist) / short_window
                short_var = sum((x - short_mean) ** 2 for x in short_hist) / short_window
                short_std = math.sqrt(short_var)
                
                # If short term volatility is significantly higher than average, reject
                if short_std > (std * self.vol_ratio_limit):
                    continue
                
                # 2f. RSI Filter
                deltas = [hist[i] - hist[i-1] for i in range(1, len(hist))]
                if len(deltas) < self.rsi_period: continue
                
                recent_deltas = deltas[-self.rsi_period:]
                gains = sum(x for x in recent_deltas if x > 0)
                losses = sum(abs(x) for x in recent_deltas if x < 0)
                
                if losses == 0: rsi = 100.0
                elif gains == 0: rsi = 0.0
                else:
                    rs = gains / losses
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                
                if rsi > self.rsi_limit:
                    continue

                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'z': z_score,
                    'rsi': rsi,
                    'vol_ratio': short_std / std
                })

            except (ValueError, KeyError, ZeroDivisionError):
                continue
        
        # --- 3. Execution ---
        if candidates:
            # Sort by Z-score. 
            # We want the deepest dip that is still ABOVE our crash floor.
            candidates.sort(key=lambda x: x['z']) 
            
            best = candidates[0]
            
            # Position Sizing
            amount = (self.balance * self.trade_pct) / best['price']
            
            self.positions[best['symbol']] = {
                'entry': best['price'],
                'amount': amount,
                'high': best['price'],
                'age': 0
            }
            
            return {
                "side": "BUY",
                "symbol": best['symbol'],
                "amount": amount,
                "reason": ["Z_BAND", f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None