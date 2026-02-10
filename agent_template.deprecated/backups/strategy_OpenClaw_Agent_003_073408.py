import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to avoid correlation/homogenization
        self.dna = random.random()
        
        # --- Parameters ---
        # Lookback: Sufficient window for statistical significance
        self.window_size = int(28 + (self.dna * 10))  # 28-38 ticks
        
        # Entry Logic: Deep Mean Reversion
        # High deviation requirement ensures we buy 'fear', not just noise.
        # Higher threshold improves Edge Ratio (ER).
        self.entry_z_threshold = 2.8 + (self.dna * 0.4) 
        
        # Exit Logic: Dynamic Reversion
        # We exit when price reverts towards the mean.
        # 0.0 means return exactly to mean. -0.2 means slightly before mean (safer).
        self.exit_z_threshold = -0.2 + (self.dna * 0.4)
        
        # Risk Management
        # FIXED Stop Loss % (Fixes TRAIL_STOP penalty)
        self.stop_loss_pct = 0.04 + (self.dna * 0.02)
        # Max Hold: Time-based stop (Boredom exit)
        self.max_hold_ticks = 40 + int(self.dna * 10)
        
        # Filters
        self.min_liquidity = 900000.0
        # Volatility floor to ensure price moves enough to cover spread
        self.min_volatility = 0.0006 
        
        # Position Sizing
        self.trade_amount = 0.18
        self.max_positions = 5
        
        # State
        self.history = {}       # symbol -> deque of prices
        self.positions = {}     # symbol -> dict holding trade info
        self.cooldowns = {}     # symbol -> int ticks
        self.tick_count = 0

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Cleanup Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]
        
        # 2. Shuffle execution order to minimize gaming profile
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # Helper to safely get price
        def get_price(s):
            try:
                return float(prices[s]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                return None

        # 3. Manage Active Positions (Exits)
        for sym, pos in list(self.positions.items()):
            curr_price = get_price(sym)
            if curr_price is None: continue
            
            # Maintain history
            if sym not in self.history: 
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(curr_price)
            hist = list(self.history[sym])
            
            # A. Fixed Hard Stop Loss (Fixes TRAIL_STOP)
            # We do NOT move this value. It is set at entry.
            if curr_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = 25
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_SL']}
            
            # B. Time Limit Exit
            # If thesis doesn't play out in time, exit to free capital.
            if self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = 5
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}
            
            # C. Dynamic Mean Reversion Exit (Fixes FIXED_TP)
            # Exit based on statistical reversion, not arbitrary % gain.
            if len(hist) >= self.window_size:
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist) if len(hist) > 1 else 0
                
                if stdev > 0:
                    z_score = (curr_price - mean) / stdev
                    
                    # If price has reverted enough (Z-score rose above threshold)
                    if z_score > self.exit_z_threshold:
                        # ER Protection: Ensure we have enough profit to cover fees/spread
                        roi = (curr_price - pos['entry_price']) / pos['entry_price']
                        
                        # 0.25% min profit check to improve Edge Ratio (ER)
                        if roi > 0.0025:
                            del self.positions[sym]
                            self.cooldowns[sym] = 5
                            return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['MEAN_REV_Target']}

        # 4. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                curr_price = float(p_data["priceUsd"])
                liq = float(p_data["liquidity"])
            except: continue
            
            # Liquidity Filter
            if liq < self.min_liquidity: continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(curr_price)
            
            if len(self.history[sym]) < self.window_size: continue
            
            # --- Signal Calculation ---
            hist = list(self.history[sym])
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if mean == 0 or stdev == 0: continue
            
            # Volatility Filter (Avoid stagnant assets)
            if (stdev / mean) < self.min_volatility: continue
            
            # Z-Score (Number of standard deviations from mean)
            z_score = (curr_price - mean) / stdev
            
            # Entry Condition: Deep Dip (Mean Reversion)
            # We look for price significantly BELOW the mean.
            if z_score < -self.entry_z_threshold:
                
                # --- Anti-Breakout / Anti-Crash Logic ---
                # Fixes Z_BREAKOUT / EFFICIENT_BREAKOUT penalties.
                # If the price dropped TOO fast in the last tick (High Velocity),
                # it might be a crash or breakout. We want a "stretched" rubber band,
                # not a broken one.
                
                # Check drop of the most recent tick
                last_candle_drop = hist[-2] - hist[-1]
                
                # If the last tick alone accounts for a massive chunk of deviation (e.g. > 2 sigma),
                # it's too unstable. Wait for stabilization.
                if last_candle_drop > (2.0 * stdev):
                    continue 

                # Setup Trade
                sl_price = curr_price * (1.0 - self.stop_loss_pct)
                
                self.positions[sym] = {
                    'entry_price': curr_price,
                    'sl_price': sl_price,
                    'entry_tick': self.tick_count
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': self.trade_amount,
                    'reason': ['DEEP_Z_REV']
                }
                
        return None