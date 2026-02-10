import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18
        
        # === Filters ===
        # Increased thresholds to ensure high-quality order books
        self.min_liquidity = 8000000.0   # 8M USD
        self.min_volume = 3000000.0      # 3M USD
        
        # === Entry Logic Parameters ===
        self.lookback = 50
        
        # Fix for 'Z:-3.93':
        # We define a "Safe Dip Zone". 
        # We avoid buying dips that are TOO deep (Z < -3.8), identifying them as crashes.
        self.z_min = -3.8    # Black Swan Floor (Don't buy below this)
        self.z_max = -2.2    # Entry Threshold (Must be below this)
        
        self.rsi_threshold = 26.0
        
        # === Exit Logic Parameters ===
        self.stop_loss = 0.05       # 5% Hard Stop
        self.trail_trigger = 0.012  # Start trailing at 1.2% profit
        self.trail_dist = 0.008     # 0.8% Trailing distance
        self.time_limit = 65        # Max hold ticks
        
        # === State Management ===
        self.positions = {}         # symbol -> pos_data
        self.history = {}           # symbol -> deque
        self.cooldown = {}          # symbol -> int

    def on_price_update(self, prices):
        """
        Main strategy loop.
        """
        # --- 1. Position Management (Exits) ---
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
                
                # Metrics
                roi = (curr_price - entry_price) / entry_price
                max_profit = (pos['highest'] - entry_price) / entry_price
                
                action = None
                reason = None
                
                # A. Hard Stop Loss
                if roi <= -self.stop_loss:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Dynamic Trailing Stop
                elif max_profit >= self.trail_trigger:
                    # Calculate trail stop price
                    stop_price = pos['highest'] * (1.0 - self.trail_dist)
                    if curr_price <= stop_price:
                        action = "SELL"
                        reason = "TRAILING_TP"
                
                # C. Time/Stagnation Limit
                elif pos['age'] >= self.time_limit:
                    # If we haven't made decent profit by time limit, cut it
                    if roi < 0.003: 
                        action = "SELL"
                        reason = "STAGNANT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 30 # Cooldown to prevent re-entering same bad volatility
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
            # Skip if in position or cooldown
            if sym in self.positions:
                continue
            
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]
                continue
            
            try:
                # 2a. Liquidity Filters
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue
                
                price = float(data["priceUsd"])
                
                # 2b. Update History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.lookback:
                    continue
                
                # 2c. Calculate Statistics
                hist = list(self.history[sym])
                mean = sum(hist) / len(hist)
                variance = sum((x - mean) ** 2 for x in hist) / len(hist)
                std = math.sqrt(variance)
                
                if std == 0 or mean == 0:
                    continue
                
                # Volatility Check (Avoid stablecoins or dead assets)
                cv = std / mean
                if cv < 0.002:
                    continue
                    
                z_score = (price - mean) / std
                
                # 2d. RSI Calculation
                period = 14
                deltas = [hist[i] - hist[i-1] for i in range(1, len(hist))]
                if len(deltas) < period:
                    continue
                    
                recent = deltas[-period:]
                gains = sum(x for x in recent if x > 0)
                losses = sum(abs(x) for x in recent if x < 0)
                
                if losses == 0:
                    rsi = 100.0
                elif gains == 0:
                    rsi = 0.0
                else:
                    rs = gains / losses
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                
                # 2e. Signal Validation
                
                # FIX: Cap the Z-score depth to avoid catching falling knives (Z:-3.93 penalty)
                if self.z_min <= z_score <= self.z_max:
                    
                    if rsi <= self.rsi_threshold:
                        
                        # Mutation: "Candle Clamp"
                        # Ensure the last tick didn't drop more than 2 sigmas alone (Flash Crash protection)
                        last_tick_change = hist[-1] - hist[-2]
                        if last_tick_change < 0 and abs(last_tick_change) > (2.0 * std):
                            continue

                        # Mutation: Short-term Momentum Check
                        # Check that the 5-period SMA slope is not vertical down
                        sma5 = sum(hist[-5:]) / 5
                        sma10 = sum(hist[-10:]) / 10
                        
                        # We want the price to be somewhat near the short term mean relative to the drop
                        # If price is WAY below SMA5, it's still crashing hard.
                        if price > sma5 * 0.985: 
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
            # Sort by RSI (most oversold) to prioritize mean reversion potential
            # This diverges from sorting by Z, which can lead to outliers
            best = min(candidates, key=lambda x: x['rsi'])
            
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
                "reason": ["REV_FILTERED", f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None