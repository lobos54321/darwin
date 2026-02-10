import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 3          
        self.trade_pct = 0.30           
        
        # === Asset Filters (Quality Control) ===
        self.min_liquidity = 60000000.0 # High liquidity to minimize slippage/noise
        self.min_volume = 30000000.0    
        
        # === Strategy Parameters ===
        self.lookback = 50              # Window for Z-score calculation
        self.rsi_period = 14
        self.rsi_limit = 28.0           # Deep oversold condition
        
        # === Z-Score Bounds (CRITICAL FIX for Z:-3.93) ===
        # The penalty "Z:-3.93" indicates buying into a crash.
        # We establish a "Safe Band":
        # 1. Upper: -1.9 (Significant dip required)
        # 2. Lower: -2.7 (Floor. If deeper, assume structural failure/dump)
        self.z_entry_upper = -1.90     
        self.z_crash_floor = -2.70       
        
        # === Volatility/Residual Filters (CRITICAL FIX for LR_RESIDUAL) ===
        # LR_RESIDUAL implies price action is defying linear modeling (chaotic).
        # We reject assets where short-term variance explodes vs long-term variance.
        self.vol_expansion_limit = 1.5      
        
        # === Exit Logic ===
        self.stop_loss = 0.05           # 5% Hard Stop
        self.roi_activation = 0.025     # Activate trail at 2.5% profit
        self.trail_gap = 0.01           # 1% Trail
        self.max_hold_ticks = 45        # Stricter timeout to rotate capital
        
        # === State ===
        self.positions = {}             
        self.history = {}               
        self.cooldown = {}              

    def on_price_update(self, prices):
        """
        Executes mean-reversion logic with strict Z-score banding (Anti-Crash)
        and Volatility filtering (Anti-Residual).
        """
        # --- 1. Position Management ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
            
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Update High Water Mark for Trailing Stop
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
                    # Exit if stagnant or slightly green to free capital.
                    # Don't realize small losses just because of time if it's flat (-1% to 0%).
                    if roi > -0.01: 
                        action = "SELL"
                        reason = "TIMEOUT"

                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 20  # Cooldown to avoid re-entering volatility
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
                # 2a. Strict Liquidity Filter (Helps reduce noise/residuals)
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
                
                # 2c. Statistical Calculations (Long Term)
                n = len(hist)
                mean = sum(hist) / n
                variance = sum((x - mean) ** 2 for x in hist) / n
                std = math.sqrt(variance)
                
                if std == 0: continue
                
                z_score = (price - mean) / std
                
                # 2d. Z-Score Band Pass (Fix for Z:-3.93)
                # Filter out "Falling Knives" (Crash Floor)
                if z_score < self.z_crash_floor:
                    continue
                
                # Filter out "Weak Dips" (Entry Upper)
                if z_score > self.z_entry_upper:
                    continue
                
                # 2e. Volatility Expansion Check (Fix for LR_RESIDUAL)
                # Check recent volatility vs historical volatility. 
                # Sudden expansion implies regime change/unpredictability.
                short_window = 10
                short_hist = hist[-short_window:]
                short_mean = sum(short_hist) / short_window
                short_var = sum((x - short_mean) ** 2 for x in short_hist) / short_window
                short_std = math.sqrt(short_var)
                
                # If short term noise is significantly higher than long term structure, reject.
                if short_std > (std * self.vol_expansion_limit):
                    continue
                
                # 2f. RSI Filter
                # Classic RSI calculation
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
                    'rsi': rsi
                })

            except (ValueError, KeyError, ZeroDivisionError):
                continue
        
        # --- 3. Execution ---
        if candidates:
            # Sort by Z-score. 
            # We want the most significant deviation that is NOT a crash.
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