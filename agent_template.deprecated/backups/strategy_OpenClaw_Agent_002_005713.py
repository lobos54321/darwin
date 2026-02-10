import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 3
        self.trade_pct = 0.30
        
        # === Asset Filters (Quality Control) ===
        self.min_liquidity = 70000000.0 # Increased liquidity req to avoid slippage
        self.min_volume = 35000000.0
        
        # === Strategy Parameters ===
        self.lookback = 45              # Slightly adjusted window
        self.rsi_period = 14
        self.rsi_limit = 30.0           # Strict oversold condition
        
        # === Z-Score Bounds (Fix for Z:-3.93) ===
        # We enforce a strict floor. We want "dips", not "crashes".
        # Safe Band: Buy between -1.8 and -2.6.
        # Anything below -2.6 is considered a falling knife (structural failure).
        self.z_entry_upper = -1.80
        self.z_crash_floor = -2.60
        
        # === Volatility Filter (Fix for LR_RESIDUAL) ===
        # Rejects assets where short-term volatility (chaos) spikes relative to long-term volatility.
        # Stricter limit: 1.35x expansion allowed.
        self.vol_expansion_limit = 1.35
        
        # === Unique Mutation: Trend Filter ===
        # Avoid buying dips in assets that have crashed heavily in the last 24h (>15% drop).
        # This filters out "Luna-style" death spirals.
        self.max_daily_drop = -15.0 
        
        # === Exit Logic ===
        self.stop_loss = 0.04           # 4% Hard Stop
        self.roi_activation = 0.02      # Activate trail at 2% profit
        self.trail_gap = 0.008          # 0.8% Trail
        self.max_hold_ticks = 35        # Rotate capital faster if stagnant
        
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
                
                # C. Timeout
                elif pos['age'] >= self.max_hold_ticks:
                    # Exit if profit is minimal or slightly negative to free up slot
                    if roi > -0.01: 
                        action = "SELL"
                        reason = "TIMEOUT"

                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 30 # Extended cooldown
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

                # 2b. Mutation: 24h Change Safety Check
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
                
                # 2d. Stats Calculation
                n = len(hist)
                mean = sum(hist) / n
                variance = sum((x - mean) ** 2 for x in hist) / n
                std = math.sqrt(variance)
                
                if std == 0: continue
                
                z_score = (price - mean) / std
                
                # 2e. Z-Score Band Pass (Critical Fixes)
                if z_score < self.z_crash_floor: continue # Avoids Z:-3.93 (Crash)
                if z_score > self.z_entry_upper: continue # Must be a real dip
                
                # 2f. Volatility Filter (Critical Fix for LR_RESIDUAL)
                # Check 8-tick short window vs long window
                short_window = 8
                short_hist = hist[-short_window:]
                short_mean = sum(short_hist) / short_window
                short_var = sum((x - short_mean) ** 2 for x in short_hist) / short_window
                short_std = math.sqrt(short_var)
                
                # Reject if short-term chaos is > 35% higher than normal
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
            # Sort by Z-score (Lowest is best, but we already filtered out crashes < -2.6)
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
                "reason": ["Z_BAND", f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None