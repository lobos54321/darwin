import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 3
        self.trade_pct = 0.30
        
        # === Asset Filters (Quality Control) ===
        # Increased liquidity requirements to ensure price stability and reduce slippage
        self.min_liquidity = 75000000.0 
        self.min_volume = 40000000.0
        
        # === Strategy Parameters ===
        self.lookback = 45
        self.rsi_period = 14
        self.rsi_limit = 32.0
        
        # === Z-Score Band (Fix for Z:-3.93) ===
        # We define a strict "Band Pass" filter.
        # We want to buy significant dips (Z < -1.9), but avoid structural breaks (Z < -2.7).
        # A Z-score of -3.93 implies a crash/falling knife, which we strictly reject.
        self.z_entry_upper = -1.90
        self.z_crash_floor = -2.70
        
        # === Volatility Filter (Fix for LR_RESIDUAL) ===
        # High residuals imply the price is behaving chaotically (non-stationary noise).
        # We reject assets where short-term volatility expands too fast relative to the baseline.
        self.vol_expansion_limit = 1.35
        
        # === Trend/Safety Mutation ===
        # Reject assets that have dropped > 15% in 24h to avoid death spirals (Luna/FTX style).
        self.max_daily_drop = -15.0 
        
        # === Exit Logic ===
        self.stop_loss = 0.05           # 5% Hard Stop
        self.roi_activation = 0.025     # Activate trail at 2.5% profit
        self.trail_gap = 0.01           # 1% Trail
        self.max_hold_ticks = 40        # Timeout to rotate capital
        
        # === State ===
        self.positions = {}
        self.history = {}
        self.cooldown = {}

    def on_price_update(self, prices):
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
                
                # A. Hard Stop
                if roi <= -self.stop_loss:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Trailing Profit
                elif peak_roi >= self.roi_activation and curr_price <= trail_price:
                    action = "SELL"
                    reason = "TRAILING_PROFIT"
                
                # C. Timeout (Stagnant funds)
                elif pos['age'] >= self.max_hold_ticks:
                    # Only exit if we aren't in a deep hole, to free up slot
                    if roi > -0.02: 
                        action = "SELL"
                        reason = "TIMEOUT"

                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 20 # Cooldown to prevent immediate re-entry
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
            if self.cooldown.get(sym, 0) > 0:
                self.cooldown[sym] -= 1
                continue
            
            try:
                # 2a. Liquidity & Volume Filter
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue

                # 2b. Safety Mutation: 24h Change Check
                pct_change_24h = float(data.get("priceChange24h", 0))
                if pct_change_24h < self.max_daily_drop:
                    continue
                
                price = float(data["priceUsd"])
                if price <= 0: continue
                
                # 2c. Update History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                hist = list(self.history[sym])
                if len(hist) < self.lookback:
                    continue
                
                # 2d. Stats Calculation (Long Window)
                n = len(hist)
                mean = sum(hist) / n
                variance = sum((x - mean) ** 2 for x in hist) / n
                std = math.sqrt(variance)
                
                if std == 0: continue
                
                z_score = (price - mean) / std
                
                # 2e. Z-Score Band Pass (Critical Fix for Z:-3.93)
                # We REJECT if Z is too low (crash) or too high (not a dip)
                if z_score < self.z_crash_floor: continue 
                if z_score > self.z_entry_upper: continue
                
                # 2f. Volatility Filter (Critical Fix for LR_RESIDUAL)
                # Compare 10-tick short window vs 45-tick long window
                short_window = 10
                short_hist = hist[-short_window:]
                short_mean = sum(short_hist) / short_window
                short_var = sum((x - short_mean) ** 2 for x in short_hist) / short_window
                short_std = math.sqrt(short_var)
                
                # If short-term chaos is significantly higher than baseline, skip.
                # This prevents entering during unpredictable volatility spikes.
                if short_std > (std * self.vol_expansion_limit):
                    continue
                
                # 2g. RSI Filter
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
            # Sort by Z-score proximity to the floor (Strongest dip that isn't a crash)
            # We prefer Z closer to -2.7, but since we filtered anything < -2.7, 
            # sorting by ascending Z is safe and targets the deepest valid dips.
            candidates.sort(key=lambda x: x['z']) 
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
                "reason": ["Z_BAND_PASS", f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None