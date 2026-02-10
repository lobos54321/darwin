import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 4  # Reduced from 5 to concentrate capital on highest quality setups
        self.trade_pct = 0.24   # Increased slightly per trade
        
        # === Asset Filters ===
        # Stricter liquidity/volume requirements to avoid 'LR_RESIDUAL' noise on low-cap assets
        self.min_liquidity = 12000000.0  # 12M USD
        self.min_volume = 5000000.0      # 5M USD
        
        # === Strategy Parameters ===
        self.lookback = 42              # Optimized lookback window
        
        # Fix for 'Z:-3.93' Penalty:
        # We tighten the Z-score acceptance window.
        # Z-scores below -3.2 are often indicative of structural breaks/crashes rather than mean reversion.
        self.z_floor = -3.2             # Hard Floor: Reject anything lower (Crash protection)
        self.z_ceiling = -2.1           # Entry Threshold: Must be lower than this
        
        self.rsi_limit = 28.0           # Stricter RSI condition
        self.sma_trend_window = 12      # Short-term trend context
        
        # === Exit Logic ===
        self.stop_loss = 0.055          # 5.5% Hard Stop
        self.roi_activation = 0.015     # Activate trailing stop at 1.5% profit
        self.trail_gap = 0.005          # Tight 0.5% trail to lock in gains
        self.max_hold_ticks = 60        # Time decay
        
        # === State ===
        self.positions = {}             # sym -> dict
        self.history = {}               # sym -> deque(prices)
        self.volatility_cache = {}      # sym -> float (for regime detection)
        self.cooldown = {}              # sym -> int

    def on_price_update(self, prices):
        """
        Executes trading logic on price updates.
        Returns order dict or None.
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
                if curr_price > pos['highest']:
                    pos['highest'] = curr_price
                
                pos['age'] += 1
                entry_price = pos['entry']
                roi = (curr_price - entry_price) / entry_price
                peak_roi = (pos['highest'] - entry_price) / entry_price
                
                action = None
                reason = None
                
                # A. Hard Stop Loss
                if roi <= -self.stop_loss:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Trailing Profit
                elif peak_roi >= self.roi_activation:
                    trail_price = pos['highest'] * (1.0 - self.trail_gap)
                    if curr_price <= trail_price:
                        action = "SELL"
                        reason = "TRAILING_PROFIT"
                
                # C. Time Decay / Stagnation
                elif pos['age'] >= self.max_hold_ticks:
                    if roi < 0.004:  # Force exit if not profitable enough
                        action = "SELL"
                        reason = "TIMEOUT"

                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 20  # Prevent immediate re-entry
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
            if sym in self.positions:
                continue
            
            # Manage Cooldown
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]
                continue
            
            try:
                # 2a. Data Extraction & Filtering
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue
                
                price = float(data["priceUsd"])
                
                # 2b. History Management
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.lookback:
                    continue
                
                # 2c. Statistical Calculation
                prices_hist = list(self.history[sym])
                mean = sum(prices_hist) / len(prices_hist)
                
                # Variance/StdDev
                variance = sum((x - mean) ** 2 for x in prices_hist) / len(prices_hist)
                std = math.sqrt(variance)
                
                if std == 0:
                    continue
                
                z_score = (price - mean) / std
                
                # 2d. Primary Filter: The "Safe Dip" Window
                # Addresses 'Z:-3.93' penalty by strictly rejecting extreme outliers
                if not (self.z_floor <= z_score <= self.z_ceiling):
                    continue
                
                # 2e. Secondary Filter: RSI
                # Calculate RSI on the fly
                period = 14
                changes = [prices_hist[i] - prices_hist[i-1] for i in range(1, len(prices_hist))]
                if len(changes) < period:
                    continue
                    
                recent_changes = changes[-period:]
                gains = sum(x for x in recent_changes if x > 0)
                losses = sum(abs(x) for x in recent_changes if x < 0)
                
                if losses == 0:
                    rsi = 100.0
                elif gains == 0:
                    rsi = 0.0
                else:
                    rs = gains / losses
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                
                if rsi > self.rsi_limit:
                    continue

                # 2f. Advanced Filtering (Mutation to fix LR_RESIDUAL/Overfitting)
                # Volatility Check: We want volatile assets, but not "Broken" ones.
                # If the current drop is drastically larger than recent volatility, skip.
                
                # Calculate local volatility (last 10 ticks)
                local_prices = prices_hist[-10:]
                local_mean = sum(local_prices) / 10
                local_std = math.sqrt(sum((x - local_mean) ** 2 for x in local_prices) / 10)
                
                # If current local volatility is 3x the long term std, it's a falling knife/panic.
                if local_std > (std * 3.0):
                    continue

                # Recoil Validation:
                # Ensure we aren't catching the exact falling knife.
                # Price should be slightly above the minimum of the last 3 ticks (showing support).
                last_3 = prices_hist[-3:]
                min_recent = min(last_3)
                
                # If we are AT the minimum, wait (it might go lower).
                # We want a tiny sign of life (recoil).
                if price <= min_recent:
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
            # Sort candidates by Z-score descending (closest to mean) within the safe zone
            # This is safer than sorting by lowest Z, which risks catching knives
            candidates.sort(key=lambda x: x['z'], reverse=True)
            
            best = candidates[0]
            amount = (self.balance * self.trade_pct) / best['price']
            
            self.positions[best['symbol']] = {
                'entry': best['price'],
                'amount': amount,
                'highest': best['price'],
                'age': 0
            }
            
            return {
                "side": "BUY",
                "symbol": best['symbol'],
                "amount": amount,
                "reason": ["ADAPTIVE_Z", f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None