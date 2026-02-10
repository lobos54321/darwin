import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk ===
        self.balance = 1000.0
        self.max_positions = 3            # Reduced to focus on high-quality setups
        self.trade_pct = 0.20             # 20% allocation per trade (High conviction)
        
        # === Filters (Anti-Penalty) ===
        self.min_liquidity = 5000000.0    # 5M Min Liquidity (Avoids slippage/traps)
        self.min_volatility = 0.008       # 0.8% Min Volatility (Avoids EFFICIENT_BREAKOUT)
        self.max_crash_24h = -15.0        # Avoid assets down > 15% (Avoids Falling Knives)
        
        # === Entry Hyperparameters ===
        self.window_size = 50             # 50-tick lookback
        self.entry_z = -3.1               # Extreme statistical deviation (Deep Dip)
        self.entry_rsi = 25.0             # Deep oversold momentum
        
        # === Exit Hyperparameters ===
        self.exit_z = 0.0                 # Revert to Mean
        self.exit_rsi = 75.0              # Overbought reversal
        self.max_hold_ticks = 120         # Time-based decay limit
        
        # === State ===
        self.positions = {}               # sym -> dict
        self.history = {}                 # sym -> deque

    def _get_indicators(self, price_seq):
        """
        Calculates Z-Score, Volatility, and RSI.
        """
        if len(price_seq) < self.window_size:
            return None
            
        prices = list(price_seq)
        current = prices[-1]
        
        # 1. Statistics
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0 or mean == 0:
            return None
            
        z_score = (current - mean) / std_dev
        volatility = std_dev / mean
        
        # 2. RSI (14 period)
        period = 14
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        if not changes:
            return None
            
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
            'vol': volatility,
            'rsi': rsi,
            'std': std_dev
        }

    def on_price_update(self, prices):
        """
        Strategy Loop:
        1. Manage Exits (Mean Reversion / Dynamic Stop / Time)
        2. Identify Entries (Confluence of Z-score + RSI + Bounce)
        """
        
        # --- 1. Manage Positions ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
                
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                pos['age'] += 1
                
                # Update History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(curr_price)
                
                indicators = self._get_indicators(self.history[sym])
                
                action = None
                reason = None
                
                # A. Dynamic Volatility Stop (Replaces Fixed Stop)
                # If price drops below the volatility buffer set at entry
                if curr_price < pos['stop_price']:
                    action = "SELL"
                    reason = "VOL_STOP"
                
                # B. Time Decay (Fixes Stale Trades)
                elif pos['age'] >= self.max_hold_ticks:
                    action = "SELL"
                    reason = "TIME_LIMIT"
                    
                # C. Alpha Exits (Mean Reversion or RSI Ext)
                elif indicators:
                    if indicators['z'] >= self.exit_z:
                        action = "SELL"
                        reason = "MEAN_REVERTED"
                    elif indicators['rsi'] >= self.exit_rsi:
                        action = "SELL"
                        reason = "RSI_CLIMAX"
                        
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

        # --- 2. Scan for Entries ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                liquidity = float(data.get("liquidity", 0))
                change24h = float(data.get("priceChange24h", 0))
                
                # Filter 1: Fundamental Safety
                if liquidity < self.min_liquidity:
                    continue
                if change24h < self.max_crash_24h:
                    continue # Avoid assets in freefall
                    
                # History Maintenance
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.window_size:
                    continue
                    
                ind = self._get_indicators(self.history[sym])
                if not ind:
                    continue
                    
                # Filter 2: Volatility (Ensure edge exists)
                if ind['vol'] < self.min_volatility:
                    continue
                
                # Entry Logic: Statistical + Momentum + Micro-Structure
                # 1. Z-Score < -3.1 (Extreme rarity)
                # 2. RSI < 25 (Momentum sold off)
                # 3. Price > Prev Price (Micro-reversal / Green Candle) -> Fixes Z_BREAKOUT
                prev_price = self.history[sym][-2]
                
                if (ind['z'] <= self.entry_z and 
                    ind['rsi'] <= self.entry_rsi and 
                    price > prev_price):
                    
                    candidates.append({
                        'symbol': sym,
                        'price': price,
                        'score': abs(ind['z']), # Prefer deeper deviations
                        'std': ind['std']
                    })
                    
            except (ValueError, KeyError):
                continue
        
        # Execute Best Trade
        if candidates:
            # Sort by Z-score magnitude
            best = max(candidates, key=lambda x: x['score'])
            
            sym = best['symbol']
            price = best['price']
            std = best['std']
            
            # Position Sizing
            amt = (self.balance * self.trade_pct) / price
            
            # Dynamic Risk Management: Stop is 2.5 std devs below entry
            stop_price = price - (2.5 * std)
            
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
                "reason": ["DEEP_VALUE_Z"]
            }
            
        return None