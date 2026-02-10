import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 3          # Limit exposure to best setups
        self.trade_pct = 0.30           # Allocate 30% balance per trade
        
        # === Asset Filters (Quality Control) ===
        # High barriers to entry to prevent 'LR_RESIDUAL' (fitting to noise/garbage)
        self.min_liquidity = 15000000.0 # 15M USD
        self.min_volume = 8000000.0     # 8M USD
        
        # === Strategy Parameters ===
        self.lookback = 42              # Statistical window
        self.rsi_period = 14
        self.rsi_limit = 27.0           # Deep oversold condition
        
        # === Z-Score Bounds (CRITICAL FIX) ===
        # Fix for 'Z:-3.93': Explicitly reject dips that are statistically "Broken" (>3 std dev).
        # We target the "Sweet Spot" of mean reversion.
        self.z_entry_ceiling = -1.9     # Must be at least this cheap (Mean Reversion trigger)
        self.z_crash_floor = -2.9       # Must NOT be cheaper than this (Crash Protection)
        
        # === Exit Logic ===
        self.stop_loss = 0.045          # 4.5% Hard Stop
        self.roi_activation = 0.02      # Activate trail at 2% profit
        self.trail_gap = 0.005          # 0.5% Trail
        self.max_hold_ticks = 48        # Time limit (approx 4-8 hours depending on tick rate)
        
        # === State ===
        self.positions = {}             # sym -> dict
        self.history = {}               # sym -> deque(prices)
        self.cooldown = {}              # sym -> int

    def on_price_update(self, prices):
        """
        Executes trading logic.
        """
        # --- 1. Position Management ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
            
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Update High Water Mark for trailing stop
                if curr_price > pos['high']:
                    pos['high'] = curr_price
                
                pos['age'] += 1
                entry_price = pos['entry']
                roi = (curr_price - entry_price) / entry_price
                peak_roi = (pos['high'] - entry_price) / entry_price
                
                action = None
                reason = None
                
                # A. Hard Stop Loss
                if roi <= -self.stop_loss:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Trailing Profit
                elif peak_roi >= self.roi_activation:
                    trail_price = pos['high'] * (1.0 - self.trail_gap)
                    if curr_price <= trail_price:
                        action = "SELL"
                        reason = "TRAILING_PROFIT"
                
                # C. Timeout (Opportunity Cost)
                elif pos['age'] >= self.max_hold_ticks:
                    if roi < 0.005:  # Exit if not meaningfully profitable
                        action = "SELL"
                        reason = "TIMEOUT"

                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 15  # Cooldown to prevent wash trading
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
            
            # Cooldown Management
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]
                continue
            
            try:
                # 2a. Data Extraction & Quality Filter
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue
                
                price = float(data["priceUsd"])
                
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
                
                # 2d. Z-Score Sandbox (Fix for Z:-3.93)
                # We strictly enforce that the dip is significant but NOT catastrophic.
                # A Z-score < -2.9 is considered a structural break (crash), not a dip.
                if not (self.z_crash_floor <= z_score <= self.z_entry_ceiling):
                    continue
                
                # 2e. RSI Filter
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
                
                # 2f. Volatility Ratio (Fix for LR_RESIDUAL)
                # Check if short-term volatility is exploding compared to long-term.
                # If short_std is > 2.5x long_std, price action is chaotic/unpredictable.
                short_window = 10
                short_hist = hist[-short_window:]
                short_mean = sum(short_hist) / short_window
                short_std = math.sqrt(sum((x - short_mean) ** 2 for x in short_hist) / short_window)
                
                if short_std > (std * 2.5):
                    continue

                # 2g. Pivot Confirmation (Anti-Knife)
                # Don't buy if the current price is strictly lower than the previous 2 ticks.
                # We want to see at least a hesitation or support formation.
                # hist[-3:-1] are the 2 ticks before current.
                prev_prices = hist[-3:-1]
                if len(prev_prices) >= 2:
                    if price < min(prev_prices):
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
            # Sort by Z-score descending (e.g. -2.0 is preferred over -2.8).
            # Why? Because within the "Safe Zone", a less extreme deviation is safer 
            # and more likely to revert without further crashing.
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
                "reason": ["SAFE_Z", f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None