import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Configuration ===
        self.balance = 1000.0
        self.max_positions = 5            # Increased count for diversification
        self.trade_pct = 0.18             # ~18% per trade (Leaves ~10% buffer)
        
        # === Filters (Anti-Penalty) ===
        self.min_liquidity = 10000000.0   # 10M+ Liquidity (High quality only)
        self.max_24h_change = 10.0        # Avoid assets moving > 10% (Chaotic)
        self.min_volume = 100000.0        # Ensure basic activity
        
        # === Entry Hyperparameters (Stricter) ===
        self.window_size = 55             # Lookback for Z-score
        self.entry_z = -2.85              # Deep value threshold (was -2.6)
        self.entry_rsi = 28.0             # Deep oversold (was 32)
        
        # === Exit Hyperparameters (Adaptive) ===
        self.hard_stop_pct = 0.045        # 4.5% Max risk per trade
        self.trailing_stop_pct = 0.015    # 1.5% Trailing gap
        self.activation_gain = 0.015      # Start trailing after 1.5% profit
        self.time_limit = 120             # Max hold ticks (Recycle capital)
        
        # === State ===
        self.positions = {}               # sym -> dict
        self.history = {}                 # sym -> deque

    def _get_metrics(self, price_seq):
        """
        Calculates Z-Score and RSI.
        """
        if len(price_seq) < self.window_size:
            return None
            
        prices = list(price_seq)
        current = prices[-1]
        
        # 1. Z-Score (Statistical Deviation)
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0:
            return None
            
        z_score = (current - mean) / std_dev
        
        # 2. RSI (Relative Strength Index)
        period = 14
        if len(prices) < period + 1:
            return None
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
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
            
        return {
            'z': z_score,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        """
        Strategy Loop:
        1. Manage Positions (Trailing Stops & Hard Stops).
        2. Scan for Deep Value Entries.
        """
        
        # --- 1. Position Management ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
                
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Update high-water mark for trailing logic
                if curr_price > pos['highest_price']:
                    pos['highest_price'] = curr_price
                
                pos['age'] += 1
                
                # Metrics
                entry_price = pos['entry_price']
                current_return = (curr_price - entry_price) / entry_price
                max_return = (pos['highest_price'] - entry_price) / entry_price
                
                action = None
                reason = None
                
                # A. Hard Stop Loss (Risk Control)
                if current_return <= -self.hard_stop_pct:
                    action = "SELL"
                    reason = "HARD_STOP"
                
                # B. Trailing Stop (Secure Profits)
                # Replaces FIXED_TP with dynamic trend following
                elif max_return >= self.activation_gain:
                    trail_threshold = pos['highest_price'] * (1.0 - self.trailing_stop_pct)
                    if curr_price <= trail_threshold:
                        action = "SELL"
                        reason = "TRAILING_STOP"
                        
                # C. Time Limit (Opportunity Cost)
                elif pos['age'] >= self.time_limit:
                    action = "SELL"
                    reason = "TIME_DECAY"
                    
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
                    
            except (ValueError, KeyError):
                continue

        # --- 2. Entry Scanning ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                liquidity = float(data.get("liquidity", 0))
                volume = float(data.get("volume24h", 0))
                pct_change = float(data.get("priceChange24h", 0))
                
                # Filter 1: Market Quality
                if liquidity < self.min_liquidity or volume < self.min_volume:
                    continue
                
                # Filter 2: Stability (Avoid falling knives/pump-dumps)
                if abs(pct_change) > self.max_24h_change:
                    continue
                    
                # History Maintenance
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(price)
                
                metrics = self._get_metrics(self.history[sym])
                if not metrics:
                    continue
                
                # === Entry Logic ===
                # 1. Deep Value: Z-score must be extreme (<= -2.85)
                # 2. Oversold: RSI must be very low (<= 28)
                # 3. Momentum Confirmation: Price must NOT be making a lower low in immediate ticks
                #    (Prevents EFFICIENT_BREAKOUT penalty by confirming support bounce)
                
                if (metrics['z'] <= self.entry_z and 
                    metrics['rsi'] <= self.entry_rsi):
                    
                    # Check last 3 ticks for stabilization
                    recent_prices = list(self.history[sym])[-3:]
                    if len(recent_prices) == 3:
                        # Ensure current price is ticking up from the previous
                        # Avoiding "Catching the knife"
                        if price > recent_prices[-2]:
                            candidates.append({
                                'symbol': sym,
                                'price': price,
                                'z': metrics['z']
                            })
                    
            except (ValueError, KeyError):
                continue
        
        # Execution: Pick the most statistically deviated asset
        if candidates:
            # Sort by Z-score (lowest/deepest first)
            best = min(candidates, key=lambda x: x['z'])
            
            sym = best['symbol']
            price = best['price']
            
            # Position Sizing
            amt = (self.balance * self.trade_pct) / price
            
            self.positions[sym] = {
                'entry_price': price,
                'amount': amt,
                'age': 0,
                'highest_price': price  # Init for trailing stop
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amt,
                "reason": ["DEEP_VALUE_Z"]
            }
            
        return None