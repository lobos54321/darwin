import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 3          
        self.trade_pct = 0.30           
        
        # === Asset Filters (Quality Control) ===
        # Increased thresholds to prevent 'LR_RESIDUAL' (noise fitting)
        self.min_liquidity = 20000000.0 
        self.min_volume = 10000000.0    
        
        # === Strategy Parameters ===
        self.lookback = 50              # Increased window for statistical stability
        self.rsi_period = 14
        self.rsi_limit = 30.0           
        
        # === Z-Score Bounds (CRITICAL FIX) ===
        # Fix for 'Z:-3.93': We reject "falling knives".
        # We buy dips that are statistically significant (-1.8) 
        # but NOT structural breaks (below -2.9).
        self.z_entry_ceiling = -1.80     
        self.z_crash_floor = -2.90       
        
        # === Volatility Filter ===
        self.vol_ratio_limit = 2.0      # Reject if short-term vol is 2x long-term vol
        
        # === Exit Logic ===
        self.stop_loss = 0.05           # 5% Hard Stop
        self.roi_activation = 0.025     # Activate trail at 2.5% profit
        self.trail_gap = 0.005          # 0.5% Trail
        self.max_hold_ticks = 48        
        
        # === State ===
        self.positions = {}             
        self.history = {}               
        self.cooldown = {}              

    def on_price_update(self, prices):
        """
        Executes trading logic with strict statistical filters.
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
                
                # C. Timeout
                elif pos['age'] >= self.max_hold_ticks:
                    # Only exit if we are not deep red, otherwise hold for potential recovery 
                    # unless it hits stop loss.
                    if roi > -0.01: 
                        action = "SELL"
                        reason = "TIMEOUT"

                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 10  
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
            
            # Cooldown
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]
                continue
            
            try:
                # 2a. Liquidity Filter
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue
                
                price = float(data["priceUsd"])
                if price <= 0: continue
                
                # 2b. History Update
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                hist = list(self.history[sym])
                if len(hist) < self.lookback:
                    continue
                
                # 2c. Statistical Calculation
                mean = sum(hist) / len(hist)
                variance = sum((x - mean) ** 2 for x in hist) / len(hist)
                std = math.sqrt(variance)
                
                if std == 0: continue
                
                z_score = (price - mean) / std
                
                # 2d. Z-Score Band Pass (Fix for Z:-3.93)
                # Reject extreme crashes (< -2.9) and insignificant dips (> -1.8)
                if not (self.z_crash_floor <= z_score <= self.z_entry_ceiling):
                    continue
                
                # 2e. Volatility Stability (Fix for LR_RESIDUAL)
                # Reject if short-term volatility is exploding (market is chaotic)
                short_window = 10
                short_hist = hist[-short_window:]
                short_mean = sum(short_hist) / short_window
                short_std = math.sqrt(sum((x - short_mean) ** 2 for x in short_hist) / short_window)
                
                if short_std > (std * self.vol_ratio_limit):
                    continue
                
                # 2f. RSI Filter
                deltas = [hist[i] - hist[i-1] for i in range(1, len(hist))]
                if len(deltas) < self.rsi_period: continue
                
                recent = deltas[-self.rsi_period:]
                gains = sum(x for x in recent if x > 0)
                losses = sum(abs(x) for x in recent if x < 0)
                
                if losses == 0: rsi = 100.0
                elif gains == 0: rsi = 0.0
                else:
                    rs = gains / losses
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                
                if rsi > self.rsi_limit:
                    continue
                
                # 2g. Pivot Confirmation
                # Ensure price is not the absolute lowest of the immediate timeframe
                # This prevents catching the exact bottom of a red candle
                if len(hist) >= 3:
                    recent_low = min(hist[-3:-1]) # Low of previous 2 ticks
                    if price < recent_low * 0.995: # If breaking support by > 0.5%
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
            # Sort by Z-score descending (-1.9 is better/safer than -2.8)
            candidates.sort(key=lambda x: x['z'], reverse=True)
            
            best = candidates[0]
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