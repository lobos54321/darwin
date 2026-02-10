import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 5             # Diversification to reduce variance
        self.trade_pct = 0.19              # ~19% per trade (leaving cash buffer)
        
        # === Asset Quality Filters (Fix for ER:0.004) ===
        self.min_liquidity = 7000000.0     # 7M+ Liquidity (High quality only)
        self.min_volume = 1500000.0        # 1.5M+ Volume (Active markets)
        self.max_churn = 0.5               # Vol/Liq ratio < 0.5 (Avoid pump-and-dump churn)
        
        # === Entry Hyperparameters (Mean Reversion) ===
        self.lookback = 70                 # Extended window for statistical significance
        self.entry_z = -3.25               # Deep statistical anomaly (3.25 std devs)
        self.entry_rsi = 22.0              # Extreme oversold condition
        self.dip_confirmation_window = 3   # For detecting V-shape bounces
        
        # === Exit Hyperparameters (Fix for FIXED_TP) ===
        self.stop_loss_pct = 0.08          # 8% Hard Stop (Catastrophe avoidance)
        self.trail_trigger = 0.015         # Activate trailing stop after 1.5% profit
        self.trail_dist = 0.01             # 1% Trailing Distance
        self.time_limit = 90               # Max ticks to hold a stagnant trade
        
        # === State ===
        self.positions = {}                # sym -> dict of position details
        self.history = {}                  # sym -> deque of prices
        self.cooldown = {}                 # sym -> ticks remaining

    def _calculate_stats(self, prices):
        """
        Computes Z-Score and RSI from a price deque.
        """
        if len(prices) < self.lookback:
            return None
        
        data = list(prices)
        current = data[-1]
        
        # 1. Z-Score (Volatility Adjusted)
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0:
            return None
            
        z_score = (current - mean) / std_dev
        
        # 2. RSI (Relative Strength Index)
        period = 14
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        if len(changes) < period:
            return None
            
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
            
        return {'z': z_score, 'rsi': rsi, 'std': std_dev}

    def on_price_update(self, prices):
        """
        Main Loop:
        1. Updates position states and executes Dynamic Exits (Trailing Stops).
        2. Scans for Deep Value entries (Mean Reversion) avoiding Efficient Breakouts.
        """
        
        # --- 1. Position Management (Dynamic Exits) ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
            
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Update High Water Mark for Trailing Stop
                if curr_price > pos['highest']:
                    pos['highest'] = curr_price
                
                pos['age'] += 1
                
                # Calculate ROI
                entry_price = pos['entry']
                roi = (curr_price - entry_price) / entry_price
                max_drawdown_roi = (curr_price - pos['highest']) / pos['highest']
                max_profit_roi = (pos['highest'] - entry_price) / entry_price
                
                action = None
                reason = None
                
                # A. Hard Stop Loss
                if roi <= -self.stop_loss_pct:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Dynamic Trailing Stop (Replaces Fixed TP)
                # Only active if we've reached the trigger profit level
                elif max_profit_roi >= self.trail_trigger:
                    # Calculate dynamic stop price
                    stop_price = pos['highest'] * (1.0 - self.trail_dist)
                    if curr_price <= stop_price:
                        action = "SELL"
                        reason = "TRAILING_STOP"
                
                # C. Time/Stagnation Exit
                elif pos['age'] >= self.time_limit and roi < 0.005:
                    action = "SELL"
                    reason = "STAGNANT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    # Set cooldown to prevent immediate re-entry
                    self.cooldown[sym] = 20
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
                    
            except (ValueError, KeyError):
                continue

        # --- 2. Entry Logic (Deep Dip & Filter) ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            # Skip if active position or cooldown
            if sym in self.positions:
                continue
                
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]
                continue
                
            try:
                price = float(data["priceUsd"])
                liquidity = float(data.get("liquidity", 0))
                volume = float(data.get("volume24h", 0))
                
                # Data Integrity & Quality Filters
                if liquidity < self.min_liquidity or volume < self.min_volume:
                    continue
                
                # Churn Filter: High volume relative to liquidity indicates instability
                if liquidity > 0 and (volume / liquidity) > self.max_churn:
                    continue
                
                # Maintain History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.lookback:
                    continue
                
                # Calculate Indicators
                stats = self._calculate_stats(self.history[sym])
                if not stats:
                    continue
                
                z = stats['z']
                rsi = stats['rsi']
                
                # === Deep Value Conditions ===
                # 1. Statistical Reversion: Price is > 3.25 sigmas below mean
                # 2. Oscillator: RSI is deeply oversold (< 22)
                if z <= self.entry_z and rsi <= self.entry_rsi:
                    
                    # 3. Micro-Structure Confirmation (Anti-Knife)
                    # We check the last 3 ticks to ensure we aren't catching a falling knife
                    # Pattern: Low -> Higher -> Higher (Stabilization) or just a simple uptick check
                    # Strictly avoiding "Efficient Breakout" by ensuring we are well below mean (-Z)
                    
                    recent = list(self.history[sym])[-3:]
                    if len(recent) == 3:
                        # V-Shape or Stabilization check:
                        # Ensure momentum is slowing or turning
                        p1, p2, p3 = recent[-3], recent[-2], recent[-1]
                        
                        # Confirm local bottom (p2 was the low, p3 is recovering)
                        if p3 > p2 and p2 <= p1:
                            candidates.append({
                                'symbol': sym,
                                'price': price,
                                'z': z,
                                'rsi': rsi
                            })
                            
            except (ValueError, KeyError):
                continue
                
        # Execution: Select the single most statistically deviated asset
        if candidates:
            # Sort by Z-score (lowest/most negative first)
            best_setup = min(candidates, key=lambda x: x['z'])
            
            sym = best_setup['symbol']
            price = best_setup['price']
            
            amount = (self.balance * self.trade_pct) / price
            
            self.positions[sym] = {
                'entry': price,
                'amount': amount,
                'highest': price,
                'age': 0
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["ADAPTIVE_DIP", f"Z:{best_setup['z']:.2f}"]
            }
            
        return None