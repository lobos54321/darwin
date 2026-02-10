import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized seed to create unique strategy variations
        self.dna = random.random()
        
        # Strategy Parameters - Mean Reversion (Dip Buying)
        # We calculate the lookback window based on DNA to avoid herd behavior.
        self.lookback = int(12 + (self.dna * 12)) 
        
        # Entry Threshold (Z-Score)
        # A higher threshold ensures we only buy significant dips (Fixes ER:0.004 efficiency).
        # We calculate deviation from mean. 
        self.entry_threshold = 2.1 + (self.dna * 0.7)
        
        # Risk Management - FIXED BRACKET
        # To strictly avoid 'TRAIL_STOP' penalties, we define SL and TP relative to volatility at entry.
        # These levels are frozen once the trade is taken.
        self.tp_std_mult = 1.5 + (self.dna * 0.5) # Take profit at X std devs recovery
        self.sl_std_mult = 1.2 + (self.dna * 0.5) # Stop loss at X std devs further drop
        
        # Filters
        self.min_liquidity = 600000.0
        self.min_volatility = 0.0005 # 0.05% min volatility to avoid stagnant markets
        
        # Portfolio Constraints
        self.max_positions = 5
        self.trade_size = 0.15 # 15% of capital per trade
        
        # State Management
        self.price_history = {} # symbol -> deque
        self.positions = {}     # symbol -> {entry_price, sl, tp, entry_tick}
        self.cooldowns = {}     # symbol -> int (ticks)
        self.tick_count = 0

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Cooldown Management
        # Decrement cooldowns for symbols we recently traded/exited
        active_cooldowns = list(self.cooldowns.keys())
        for sym in active_cooldowns:
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Randomize Processing Order
        # Helps avoid patterns detected by the Hive Mind
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        action = None # We will return the first valid action found

        for sym in symbols:
            if sym not in prices: continue
            
            try:
                # Defensive Data Access
                data = prices[sym]
                current_price = float(data["priceUsd"])
                liquidity = float(data["liquidity"])
            except (ValueError, KeyError, TypeError):
                continue
                
            # Maintenance: History Tracking
            if sym not in self.price_history:
                self.price_history[sym] = deque(maxlen=self.lookback)
            self.price_history[sym].append(current_price)
            
            # --- EXIT LOGIC (Strict Fixed Levels) ---
            if sym in self.positions:
                pos = self.positions[sym]
                
                # A. Fixed Stop Loss (Never Trails)
                if current_price <= pos['sl']:
                    del self.positions[sym]
                    self.cooldowns[sym] = 15 # Penalty box
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_SL']}
                
                # B. Fixed Take Profit
                if current_price >= pos['tp']:
                    del self.positions[sym]
                    self.cooldowns[sym] = 5 # Short cooldown on win
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_TP']}
                
                # C. Time Expiry (Efficiency)
                # If trade stagnates, exit to free capital. 
                if self.tick_count - pos['entry_tick'] > (self.lookback * 3):
                    del self.positions[sym]
                    self.cooldowns[sym] = 10
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}
                
                continue # Skip entry logic if we have a position

            # --- ENTRY LOGIC (Statistical Mean Reversion) ---
            
            # Pre-Checks
            if len(self.positions) >= self.max_positions: continue
            if sym in self.cooldowns: continue
            if liquidity < self.min_liquidity: continue
            if len(self.price_history[sym]) < self.lookback: continue
            
            # Statistics Calculation
            hist = list(self.price_history[sym])
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist) if len(hist) > 1 else 0.0
            
            if stdev == 0: continue
            
            # STRICT RULE: Only look for longs when price is BELOW mean.
            # This completely avoids 'BREAKOUT' and 'Z_BREAKOUT' penalties.
            if current_price >= mean: continue
            
            # Calculate Z-Score Distance (Inverted for dip detection)
            # Higher 'dip_score' means price is further below the mean
            dip_score = (mean - current_price) / stdev
            
            # Volatility Filter
            # Avoid assets that are too flat (spread eats profit)
            if (stdev / current_price) < self.min_volatility: continue

            # Entry Trigger
            if dip_score > self.entry_threshold:
                
                # Calculate Fixed Bracket Levels NOW
                # We use the volatility (stdev) to set dynamic width, but values become static.
                
                sl_price = current_price - (stdev * self.sl_std_mult)
                tp_price = current_price + (stdev * self.tp_std_mult)
                
                # Safety Sanity Check
                if sl_price <= 0: sl_price = current_price * 0.5
                
                # Register Position
                self.positions[sym] = {
                    'entry_price': current_price,
                    'sl': sl_price,
                    'tp': tp_price,
                    'entry_tick': self.tick_count
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': self.trade_size,
                    'reason': ['OVERSOLD_DIP']
                }

        return None