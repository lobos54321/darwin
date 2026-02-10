import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk ===
        self.balance = 1000.0
        self.max_positions = 4
        # Allocate ~24% per trade to utilize ~96% of capital
        self.trade_pct = 0.24
        
        # === Asset Filters (Quality Control) ===
        self.min_liquidity = 5000000.0   # 5M+ Liquidity
        self.min_volume = 500000.0       # 500k+ Volume
        self.max_churn_ratio = 0.8       # Vol/Liq ratio (Avoid panic selling/high turnover)
        self.max_24h_drop = -15.0        # Don't catch falling knives dropping > 15% in 24h
        
        # === Entry Hyperparameters (Stricter for High ER) ===
        self.lookback = 60               # Longer window for robust Z-score
        self.entry_z = -3.1              # Extreme statistical deviation (was -2.85)
        self.entry_rsi = 24.0            # Deep oversold (was 28)
        
        # === Exit Hyperparameters (Dynamic) ===
        self.hard_stop_pct = 0.06        # 6% Max Risk
        self.trail_activation = 0.015    # Start trailing after 1.5% profit
        self.trail_dist_base = 0.02      # Base trailing distance (2%)
        self.trail_dist_tight = 0.01     # Tighten to 1% if profit > 5%
        self.max_hold_ticks = 80         # Time limit for stagnant trades
        
        # === State Management ===
        self.positions = {}              # sym -> {entry, amount, highest, age}
        self.history = {}                # sym -> deque

    def _get_indicators(self, price_seq):
        """
        Calculates Z-Score and RSI with strict error handling.
        """
        if len(price_seq) < self.lookback:
            return None
            
        prices = list(price_seq)
        current = prices[-1]
        
        # 1. Z-Score
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0:
            return None
            
        z_score = (current - mean) / std_dev
        
        # 2. RSI (14 period)
        period = 14
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
            
        return {'z': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        """
        Core Logic:
        1. Dynamic Exit Management (Trailing Stops).
        2. Deep Value Entry Scanning (Statistical Reversion).
        """
        
        # --- 1. Manage Active Positions ---
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
                
                # Metrics
                entry_price = pos['entry']
                roi = (curr_price - entry_price) / entry_price
                max_roi = (pos['highest'] - entry_price) / entry_price
                
                action = None
                reason = None
                
                # A. Hard Stop (Catastrophe Protection)
                if roi <= -self.hard_stop_pct:
                    action = "SELL"
                    reason = "HARD_STOP"
                
                # B. Dynamic Trailing Stop (Replaces Fixed TP)
                elif max_roi >= self.trail_activation:
                    # Adaptive Trail: Tighten if we have significant profit
                    trail_dist = self.trail_dist_tight if max_roi > 0.05 else self.trail_dist_base
                    stop_price = pos['highest'] * (1.0 - trail_dist)
                    
                    if curr_price <= stop_price:
                        action = "SELL"
                        reason = "TRAILING_STOP"
                        
                # C. Time Decay (Opportunity Cost)
                # Only sell if we are stagnant/losing. Let winners run.
                elif pos['age'] >= self.max_hold_ticks and roi < 0.01:
                    action = "SELL"
                    reason = "STAGNANT"
                    
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

        # --- 2. Scan for New Entries ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                
                # History Update
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.lookback:
                    continue
                
                # Basic Filters (Liquidity & Stability)
                liquidity = float(data.get("liquidity", 0))
                volume = float(data.get("volume24h", 0))
                change_24h = float(data.get("priceChange24h", 0))
                
                if liquidity < self.min_liquidity or volume < self.min_volume:
                    continue
                
                # Filter: High Churn (Volume/Liq ratio) often precedes crashes
                if liquidity > 0 and (volume / liquidity) > self.max_churn_ratio:
                    continue
                    
                # Filter: Don't catch falling knives that are crashing too hard daily
                if change_24h < self.max_24h_drop:
                    continue

                # Calculate Indicators
                metrics = self._get_indicators(self.history[sym])
                if not metrics:
                    continue
                
                # === Entry Logic ===
                # 1. Z-Score must be statistically extreme (Mean Reversion)
                # 2. RSI must be in deep oversold territory
                if metrics['z'] <= self.entry_z and metrics['rsi'] <= self.entry_rsi:
                    
                    # 3. Micro-Structure Confirmation (Anti-Efficient Breakout)
                    # Require that the price has ticked UP from the local low
                    # This prevents buying the exact moment of a crash continuation
                    recent_prices = list(self.history[sym])[-3:]
                    if len(recent_prices) == 3:
                        # Pattern: Previous price was lower than current (Bounce started)
                        if price > recent_prices[-2]:
                            candidates.append({
                                'symbol': sym,
                                'price': price,
                                'z': metrics['z']
                            })
                            
            except (ValueError, KeyError):
                continue
        
        # Execution: Select best setup
        if candidates:
            # Sort by Z-score (Deepest statistical value)
            best_setup = min(candidates, key=lambda x: x['z'])
            
            sym = best_setup['symbol']
            price = best_setup['price']
            
            # Position Sizing
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
                "reason": ["ADAPTIVE_DIP"]
            }
            
        return None