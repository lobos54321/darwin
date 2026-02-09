import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk ===
        self.balance = 1000.0
        self.max_positions = 5            # Max concurrent positions
        self.trade_pct = 0.18             # Allocation per trade
        
        # === Filters (Addressing ER:0.004) ===
        # Stricter requirements to ensure asset quality
        self.min_liquidity = 7000000.0    # 7M USD Liquidity
        self.min_volume = 2500000.0       # 2.5M USD Volume
        self.min_volatility = 0.004       # Min volatility to ensure profit potential
        
        # === Entry Logic (Addressing EFFICIENT_BREAKOUT) ===
        # Deep Mean Reversion with Micro-Structure Confirmation
        self.lookback = 50
        self.entry_z = -2.8               # Moderate deviation for dip
        self.entry_rsi = 28.0             # Oversold threshold
        
        # === Exit Logic (Addressing FIXED_TP) ===
        # Dynamic Trailing Stop
        self.sl_pct = 0.06                # 6% Hard Stop
        self.trail_trigger = 0.015        # Start trailing at 1.5% profit
        self.trail_dist = 0.01            # 1% Trailing distance
        self.time_limit = 70              # Max hold ticks
        
        # === State ===
        self.positions = {}               # symbol -> position_data
        self.history = {}                 # symbol -> price_deque
        self.cooldown = {}                # symbol -> ticks

    def _get_stats(self, data_deque):
        """Calculates Z-Score, RSI, and Coefficient of Variation."""
        if len(data_deque) < self.lookback:
            return None
            
        data = list(data_deque)
        current_price = data[-1]
        
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std_dev = math.sqrt(variance)
        
        if mean == 0 or std_dev == 0:
            return None
            
        # Volatility Filter (CV)
        cv = std_dev / mean
        if cv < self.min_volatility:
            return None
            
        z_score = (current_price - mean) / std_dev
        
        # RSI
        period = 14
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        if len(deltas) < period:
            return None
            
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
            
        return {'z': z_score, 'rsi': rsi}

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
                if curr_price > pos['highest']:
                    pos['highest'] = curr_price
                    
                pos['age'] += 1
                entry_price = pos['entry']
                
                roi = (curr_price - entry_price) / entry_price
                max_profit = (pos['highest'] - entry_price) / entry_price
                
                action = None
                reason = None
                
                # A. Hard Stop Loss
                if roi <= -self.sl_pct:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Dynamic Trailing Stop
                elif max_profit >= self.trail_trigger:
                    # Tighten trail for massive runners (>5%)
                    active_dist = self.trail_dist * (0.5 if max_profit > 0.05 else 1.0)
                    stop_price = pos['highest'] * (1.0 - active_dist)
                    
                    if curr_price <= stop_price:
                        action = "SELL"
                        reason = "TRAILING_STOP"
                
                # C. Time Limit for Stagnation
                elif pos['age'] >= self.time_limit and roi < 0.004:
                    action = "SELL"
                    reason = "STAGNANT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 30  # Cooldown period
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
            if sym in self.positions:
                continue
            
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]
                continue
                
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                # Liquidity & Volume Filters
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue
                
                # History Tracking
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.lookback:
                    continue
                    
                # Calculate Stats
                stats = self._get_stats(self.history[sym])
                if not stats:
                    continue
                
                z = stats['z']
                rsi = stats['rsi']
                
                # Signal: Deep Dip
                if z <= self.entry_z and rsi <= self.entry_rsi:
                    
                    # Mutation: "Hook" Confirmation
                    # Prevents buying a falling knife. Requires a V-shape tick pattern.
                    # P_now > P_prev AND P_prev < P_prev2
                    hist = list(self.history[sym])
                    p_now = hist[-1]
                    p_prev = hist[-2]
                    p_prev2 = hist[-3]
                    
                    if p_now > p_prev and p_prev < p_prev2:
                        candidates.append({
                            'symbol': sym,
                            'price': price,
                            'z': z,
                            'rsi': rsi
                        })
                        
            except (ValueError, KeyError):
                continue
        
        # Execution: Buy the statistically 'best' dip
        if candidates:
            best = min(candidates, key=lambda x: x['z'])
            
            amt = (self.balance * self.trade_pct) / best['price']
            
            self.positions[best['symbol']] = {
                'entry': best['price'],
                'amount': amt,
                'highest': best['price'],
                'age': 0
            }
            
            return {
                "side": "BUY",
                "symbol": best['symbol'],
                "amount": amt,
                "reason": ["HOOK_DIP", f"Z:{best['z']:.2f}"]
            }
            
        return None