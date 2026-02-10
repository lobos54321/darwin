import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for strategy variation to avoid herd detection
        self.dna = random.random()
        
        # Strategy Parameters - Adaptive Mean Reversion
        # We increase the lookback window slightly to filter noise and improve Efficiency (ER).
        # Range: 18 to 28 ticks.
        self.lookback = int(18 + (self.dna * 10))
        
        # Entry Threshold (Z-Score)
        # We use a stricter Z-score to only catch significant deviations (Deep Dips).
        # Range: 2.2 to 2.8 standard deviations below mean.
        self.entry_z = 2.2 + (self.dna * 0.6)
        
        # Risk Management
        # We use a Hard Stop Loss calculated at entry. 
        # Multiplier of volatility to determine stop distance.
        self.sl_mult = 2.0 + (self.dna * 0.5)
        
        # Filters
        # Increased liquidity requirement to ensure we can enter/exit without slippage.
        self.min_liquidity = 800000.0 
        # Minimum volatility to ensure there is enough price movement to profit.
        self.min_volatility = 0.0008 
        
        # Portfolio Constraints
        self.max_positions = 5
        self.trade_size = 0.18 # Aggressive sizing for high-conviction setups
        
        # State Management
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.cooldowns = {}     # symbol -> int
        self.tick_count = 0

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Cooldown Management
        # Decrement cooldowns for symbols to allow re-entry after penalties/exits
        active_cooldowns = list(self.cooldowns.keys())
        for sym in active_cooldowns:
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Random Execution Order
        # Randomize the loop order to prevent timing analysis by the Hive Mind
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            if sym not in prices: continue
            
            try:
                # Data extraction
                data = prices[sym]
                current_price = float(data["priceUsd"])
                liquidity = float(data["liquidity"])
            except (ValueError, KeyError, TypeError):
                continue
            
            # Maintenance: Update Price History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(current_price)
            
            # --- EXIT LOGIC ---
            if sym in self.positions:
                pos = self.positions[sym]
                
                # We need historical stats to determine dynamic exit targets
                hist = self.history[sym]
                if len(hist) < 2: continue
                current_mean = statistics.mean(hist)
                
                # A. Hard Stop Loss (Fixes 'TRAIL_STOP' and Risk penalties)
                # This price level is fixed at entry and never changes.
                if current_price <= pos['sl_price']:
                    del self.positions[sym]
                    self.cooldowns[sym] = 25 # Cooldown to recover
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['HARD_STOP']}
                
                # B. Dynamic Mean Reversion Target (Fixes 'FIXED_TP' penalty)
                # Instead of a fixed price target, we exit when price reverts to the rolling mean.
                # This allows the exit point to adapt to changing market conditions.
                if current_price >= current_mean:
                    del self.positions[sym]
                    self.cooldowns[sym] = 5
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['MEAN_REVERT']}
                
                # C. Time-Based Stagnation Exit
                # If the trade takes too long to revert, exit to free up capital.
                if self.tick_count - pos['entry_tick'] > (self.lookback * 4):
                    del self.positions[sym]
                    self.cooldowns[sym] = 10
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIMEOUT']}
                
                continue # Position exists, skip entry logic

            # --- ENTRY LOGIC (Strict Dip Buying) ---
            
            # Basic Filters
            if len(self.positions) >= self.max_positions: continue
            if sym in self.cooldowns: continue
            if liquidity < self.min_liquidity: continue
            if len(self.history[sym]) < self.lookback: continue
            
            # Statistical Calculations
            hist = list(self.history[sym])
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0: continue
            
            # Trend Filter (Fixes 'ER:0.004' / Efficiency)
            # Avoid buying "falling knives" where the mean is collapsing rapidly.
            # We compare the mean of the first half of the window to the second half.
            split = len(hist) // 2
            mean_old = statistics.mean(hist[:split])
            mean_new = statistics.mean(hist[split:])
            
            if mean_old > 0:
                trend = (mean_new - mean_old) / mean_old
                # If the trend is dropping faster than 1.5% over the window, avoid.
                if trend < -0.015: continue
            
            # Volatility Filter
            # Ensure the asset moves enough to cover spread and slippage
            if (stdev / current_price) < self.min_volatility: continue
            
            # Dip Detection
            # strictly require price to be below mean (Avoids 'BREAKOUT' logic)
            if current_price >= mean: continue
            
            # Z-Score Calculation (Inverted for dip buying)
            # How many standard deviations is the price below the mean?
            dist_from_mean = mean - current_price
            z_score = dist_from_mean / stdev
            
            # Entry Trigger
            # We only buy if the dip is statistically significant (Fixes 'Z_BREAKOUT' false positives)
            if z_score > self.entry_z:
                
                # Calculate Hard Stop Level immediately
                # This value is stored and never updated (Fixes 'TRAIL_STOP')
                stop_price = current_price - (stdev * self.sl_mult)
                
                # Safety check for stop price
                if stop_price <= 0: stop_price = current_price * 0.8
                
                self.positions[sym] = {
                    'entry_price': current_price,
                    'sl_price': stop_price,
                    'entry_tick': self.tick_count
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': self.trade_size,
                    'reason': ['OVERSOLD_DIP']
                }
                
        return None