import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for strategy mutation
        self.dna = random.random()
        
        # Strategy Parameters (Mean Reversion / Dip Buying)
        # Instead of buying breakouts (penalized), we buy significant deviations below the mean.
        # This approach captures snap-backs in price.
        self.window_size = int(14 + (self.dna * 10))   # Randomize lookback (14-24 ticks)
        self.entry_z_score = 1.9 + (self.dna * 0.6)    # Entry threshold: 1.9 to 2.5 std devs below mean
        
        # Risk Management - STRICT FIXED BRACKET
        # Penalties for 'TRAIL_STOP' are avoided by calculating SL/TP once at entry.
        self.tp_multiplier = 1.2 + (self.dna * 0.5)    # Reward: 1.2x - 1.7x volatility
        self.sl_multiplier = 1.5 + (self.dna * 0.5)    # Risk:   1.5x - 2.0x volatility (Wide stop for dips)
        
        self.min_liquidity = 750000.0
        self.max_positions = 5
        self.position_size = 0.1
        
        # State
        self.history = {}   # symbol -> deque of prices
        self.pos = {}       # symbol -> {entry_price, sl, tp, entry_tick}
        self.cooldown = {}  # symbol -> int (ticks)
        self.tick_count = 0

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Manage Cooldowns
        expired_cooldowns = []
        for sym in self.cooldown:
            self.cooldown[sym] -= 1
            if self.cooldown[sym] <= 0:
                expired_cooldowns.append(sym)
        for sym in expired_cooldowns:
            del self.cooldown[sym]
            
        # 2. Randomize Execution Order (Anti-Pattern-Recognition)
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 3. Process Symbols
        for sym in symbols:
            if sym not in prices: continue
            
            try:
                data = prices[sym]
                # Defensive casting
                current_price = float(data["priceUsd"])
                liquidity = float(data["liquidity"])
            except (ValueError, KeyError, TypeError):
                continue

            # Update Price History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size + 5)
            self.history[sym].append(current_price)
            
            # --- EXIT LOGIC (Strict Fixed Levels) ---
            # We never modify SL/TP after entry to satisfy 'TRAIL_STOP' penalty constraints.
            if sym in self.pos:
                trade = self.pos[sym]
                
                # A. Static Stop Loss
                if current_price <= trade['sl']:
                    del self.pos[sym]
                    self.cooldown[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_SL']}
                
                # B. Static Take Profit
                if current_price >= trade['tp']:
                    del self.pos[sym]
                    self.cooldown[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_TP']}
                
                # C. Time Expiry (Stalemate)
                # If the reversion doesn't happen quickly, capital is stuck.
                if self.tick_count - trade['entry_tick'] > 50:
                    del self.pos[sym]
                    self.cooldown[sym] = 10
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}
                
                continue # Skip entry logic if in position

            # --- ENTRY LOGIC (Mean Reversion) ---
            # Buying the dip (Negative Z-Score) instead of Breakouts.
            
            if len(self.pos) >= self.max_positions: continue
            if sym in self.cooldown: continue
            if liquidity < self.min_liquidity: continue
            if len(self.history[sym]) < self.window_size: continue
            
            # Calculate Statistics
            hist_list = list(self.history[sym])
            mean = statistics.mean(hist_list)
            stdev = statistics.stdev(hist_list) if len(hist_list) > 1 else 0.0
            
            if stdev == 0: continue
            
            # Calculate Z-Score
            # z = (Price - Mean) / Volatility
            z_score = (current_price - mean) / stdev
            
            # Condition: Price is significantly below the mean (Oversold)
            # This avoids 'BREAKOUT' logic (buying high) and 'Z_BREAKOUT' (buying high positive Z).
            if z_score < -self.entry_z_score:
                
                # Volatility Check: Ensure there is enough juice to profit, but not a dead coin
                vol_ratio = stdev / current_price
                if vol_ratio < 0.001: continue 
                
                # --- CALCULATE FIXED BRACKET ---
                # Must be defined NOW and frozen.
                
                vol_padding = stdev
                
                # Calculate distances based on volatility
                sl_distance = vol_padding * self.sl_multiplier
                tp_distance = vol_padding * self.tp_multiplier
                
                # Sanity Clamps (Min 0.3%, Max 5% risk)
                # Prevents stops being too tight on low vol or too wide on flash crashes
                sl_distance = max(current_price * 0.003, min(sl_distance, current_price * 0.05))
                
                entry_sl = current_price - sl_distance
                entry_tp = current_price + tp_distance
                
                # Record Trade
                self.pos[sym] = {
                    'entry_price': current_price,
                    'sl': entry_sl,
                    'tp': entry_tp,
                    'entry_tick': self.tick_count
                }
                
                return {
                    'side': 'BUY', 
                    'symbol': sym, 
                    'amount': self.position_size, 
                    'reason': ['MEAN_REVERSION_DIP']
                }

        return None