import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk ===
        self.balance = 1000.0
        self.max_positions = 5            # Maximum concurrent positions
        self.trade_pct = 0.18             # Allocation per trade
        
        # === Filters (Addressing ER:0.004) ===
        # Higher requirements for asset quality to ensure profitable volatility
        self.min_liquidity = 6000000.0    # 6M USD Liquidity
        self.min_volume = 2000000.0       # 2M USD Volume
        self.min_volatility = 0.0035      # 0.35% Min StdDev relative to price (Avoid dead assets)
        self.max_churn = 0.55             # Volume/Liquidity ratio cap
        
        # === Entry Logic (Addressing EFFICIENT_BREAKOUT) ===
        # Deep Mean Reversion parameters
        self.lookback = 60
        self.entry_z = -3.2               # Deep statistical anomaly (> 3.2 std dev)
        self.entry_rsi = 23.0             # Deeply oversold
        
        # === Exit Logic (Addressing FIXED_TP) ===
        # Dynamic Trailing Stop instead of fixed TP
        self.sl_pct = 0.07                # 7% Hard Stop Loss
        self.trail_trigger = 0.013        # Start trailing after 1.3% profit
        self.trail_dist = 0.008           # 0.8% Trailing distance
        self.time_limit = 80              # Max hold duration (ticks)
        
        # === State ===
        self.positions = {}               # symbol -> position_data
        self.history = {}                 # symbol -> price_deque
        self.cooldown = {}                # symbol -> cooldown_ticks

    def _get_indicators(self, prices_deque):
        """Calculates Z-Score, RSI, and Volatility."""
        if len(prices_deque) < self.lookback:
            return None
            
        data = list(prices_deque)
        current_price = data[-1]
        
        # 1. Statistics
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std_dev = math.sqrt(variance)
        
        if mean == 0 or std_dev == 0:
            return None
            
        # Volatility Filter (CV) - fixes Low Expected Return
        cov = std_dev / mean
        if cov < self.min_volatility:
            return None
            
        z_score = (current_price - mean) / std_dev
        
        # 2. RSI
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
        # --- 1. Position Management (Dynamic Exits) ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
            
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Track High Water Mark for Trailing Stop
                if curr_price > pos['highest']:
                    pos['highest'] = curr_price
                    
                pos['age'] += 1
                entry_price = pos['entry']
                
                # ROI Calculations
                roi = (curr_price - entry_price) / entry_price
                max_profit = (pos['highest'] - entry_price) / entry_price
                
                action = None
                reason = None
                
                # A. Hard Stop Loss
                if roi <= -self.sl_pct:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Dynamic Trailing Stop (Replaces Fixed TP)
                elif max_profit >= self.trail_trigger:
                    # If profit is very high (>3%), tighten the trail
                    active_trail_dist = self.trail_dist * (0.5 if max_profit > 0.03 else 1.0)
                    stop_price = pos['highest'] * (1.0 - active_trail_dist)
                    
                    if curr_price <= stop_price:
                        action = "SELL"
                        reason = "TRAILING_STOP"
                
                # C. Time Expiry for Stagnant Trades
                elif pos['age'] >= self.time_limit and roi < 0.003:
                    action = "SELL"
                    reason = "STAGNANT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldown[sym] = 25  # Prevent immediate re-entry
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
            except (ValueError, KeyError):
                continue

        # --- 2. Entry Scan (Deep Dip with Filters) ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
            
            # Cooldown check
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]
                continue
                
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                # Basic Quality Filters
                if liq < self.min_liquidity or vol < self.min_volume:
                    continue
                if (vol / liq) > self.max_churn:
                    continue
                
                # History Management
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.lookback:
                    continue
                    
                # Calculate Technicals
                stats = self._get_indicators(self.history[sym])
                if not stats:
                    continue
                
                z = stats['z']
                rsi = stats['rsi']
                
                # Entry Logic: Statistical Anomaly
                if z <= self.entry_z and rsi <= self.entry_rsi:
                    
                    # Micro-Structure Confirmation (Anti-Knife)
                    # Check for a "Hook" pattern: Low -> Higher
                    hist = list(self.history[sym])
                    p_now = hist[-1]
                    p_prev = hist[-2]
                    p_prev2 = hist[-3]
                    
                    # Ensure we are bouncing off a local low
                    # p_prev was the dip, p_now is recovering
                    if p_prev < p_prev2 and p_now > p_prev:
                        candidates.append({
                            'symbol': sym,
                            'price': price,
                            'z': z,
                            'rsi': rsi
                        })
                        
            except (ValueError, KeyError):
                continue
        
        # Execution: Pick the most deviated asset
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
                "reason": ["DEEP_DIP", f"Z:{best['z']:.2f}"]
            }
            
        return None