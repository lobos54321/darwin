import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Configuration ===
        self.balance = 1000.0
        self.max_positions = 4            # Limit concurrent exposure
        self.trade_pct = 0.22             # 22% allocation (Compound growth focus)
        
        # === Filters (Strict Anti-Penalty) ===
        self.min_liquidity = 8000000.0    # 8M+ Liquidity (Avoids illiquid traps)
        self.max_volatility_entry = 0.05  # Avoid entering chaos (StdDev/Price)
        self.max_24h_change = 12.0        # Avoid assets moving > 12% (Stable Mean Reversion)
        
        # === Entry Hyperparameters ===
        self.window_size = 60             # Extended lookback for statistical significance
        self.entry_z = -2.6               # Buy the dip (Mean Reversion)
        self.entry_rsi = 32.0             # Oversold threshold
        
        # === Exit Hyperparameters ===
        self.profit_z = 0.5               # Target Band (Dynamic Take Profit)
        self.stop_loss_pct = 0.035        # 3.5% Hard Stop (Fixes TRAIL_STOP/Risk)
        self.time_limit = 140             # Max ticks to hold
        
        # === State ===
        self.positions = {}               # sym -> dict
        self.history = {}                 # sym -> deque

    def _get_metrics(self, price_seq):
        """
        Calculates robust statistics for decision making.
        """
        if len(price_seq) < self.window_size:
            return None
            
        prices = list(price_seq)
        current = prices[-1]
        
        # 1. Statistical Deviation
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0 or mean == 0:
            return None
            
        z_score = (current - mean) / std_dev
        rel_vol = std_dev / mean
        
        # 2. Relative Strength Index (14)
        period = 14
        if len(prices) < period + 1:
            return None
            
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent = changes[-period:]
        
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
            'rsi': rsi,
            'vol': rel_vol,
            'mean': mean
        }

    def on_price_update(self, prices):
        """
        Core Logic:
        1. Monitor active positions for Dynamic Profit or Hard Stop.
        2. Scan for high-probability mean reversion setups.
        """
        
        # --- 1. Position Management ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
                
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                pos['age'] += 1
                
                # Update History for Indicators
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(curr_price)
                
                metrics = self._get_metrics(self.history[sym])
                
                action = None
                reason = None
                
                # A. Hard Stop Loss (Risk Management)
                if curr_price <= pos['stop_price']:
                    action = "SELL"
                    reason = "HARD_STOP"
                
                # B. Dynamic Take Profit (Reversion to Mean+)
                # We target Z > 0.5 (Upper band of fair value)
                elif metrics and metrics['z'] >= self.profit_z:
                    action = "SELL"
                    reason = "TARGET_HIT"
                    
                # C. Time Decay (Opportunity Cost)
                elif pos['age'] >= self.time_limit:
                    action = "SELL"
                    reason = "STALE_EXIT"
                    
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
                pct_change = float(data.get("priceChange24h", 0))
                
                # Filter 1: Market Quality
                if liquidity < self.min_liquidity:
                    continue
                # Filter 2: Regime Filter (Avoid crashing/pumping assets)
                if abs(pct_change) > self.max_24h_change:
                    continue
                    
                # History Maintenance
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(price)
                
                metrics = self._get_metrics(self.history[sym])
                if not metrics:
                    continue
                
                # Filter 3: Volatility Check (Too high = unpredictable)
                if metrics['vol'] > self.max_volatility_entry:
                    continue
                
                # === Entry Logic ===
                # 1. Value: Price is statistically cheap (Z < -2.6)
                # 2. Momentum: Selling pressure exhausted (RSI < 32)
                # 3. Stabilization: Price is NOT at the absolute low of the immediate window (Avoiding Z_BREAKOUT)
                
                if (metrics['z'] <= self.entry_z and 
                    metrics['rsi'] <= self.entry_rsi):
                    
                    # Micro-Structure Check:
                    # Ensure current price > minimum of last 5 ticks (Calculated support)
                    recent_window = list(self.history[sym])[-5:]
                    local_low = min(recent_window[:-1]) # exclude current
                    
                    if price > local_low:
                        candidates.append({
                            'symbol': sym,
                            'price': price,
                            'z': metrics['z']
                        })
                    
            except (ValueError, KeyError):
                continue
        
        # Execution: Select the most undervalued asset
        if candidates:
            # Sort by Z-score (Deepest value)
            best = min(candidates, key=lambda x: x['z'])
            
            sym = best['symbol']
            price = best['price']
            
            # Position Sizing
            amt = (self.balance * self.trade_pct) / price
            
            # Set Hard Stop
            stop_price = price * (1.0 - self.stop_loss_pct)
            
            self.positions[sym] = {
                'entry_price': price,
                'amount': amt,
                'age': 0,
                'stop_price': stop_price
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amt,
                "reason": ["ADAPTIVE_REV"]
            }
            
        return None