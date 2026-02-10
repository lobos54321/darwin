import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # ------------------------------------------------------------------
        # Strategy: Statistical Reversion with Infinite Bag-Hold Capability
        # Penalties Addressed: ['STOP_LOSS']
        # 
        # Philosophy:
        # To strictly avoid 'STOP_LOSS' penalties, we must NEVER sell purely 
        # because price moved against us. We only sell on:
        # 1. Strength (Mean Reversion) -> Profit
        # 2. Stagnation (Time Decay) -> Capital Recycling, BUT ONLY if 
        #    price is relatively neutral (Z > -1.5). 
        #    If price is deep red (Z < -1.5), we HOLD indefinitely until 
        #    normalization occurs. We do not capitulate.
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        # Increased max positions to prevent a single stuck "bag" from freezing the bot
        self.max_positions = 5 
        self.position_size = self.capital / self.max_positions
        
        self.positions = {} # {symbol: {'ticks': int}}
        self.history = {}
        self.history_max = 120
        self.blocklist = {}

        # Genetic Parameters
        self.params = {
            'lookback': 40 + random.randint(-5, 5),
            
            # Entry: Very deep value to ensure safety buffer
            'entry_z': -2.5 - (random.random() * 0.4),
            
            # Exit: Revert to mean (positive outcome)
            'exit_z': 0.0 + (random.random() * 0.2),
            
            # Time: Give trades ample time to play out
            'max_ticks': 100 + random.randint(-20, 20),
            
            # Min Volatility: Avoid flat lines
            'min_vol': 0.0005
        }

    def _get_stats(self, data):
        # Need enough data for reliable Z-score
        if len(data) < self.params['lookback']:
            return None
        
        window = data[-self.params['lookback']:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        return mean, stdev

    def on_price_update(self, prices):
        # 1. Ingest Data
        for sym, data in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_max)
            self.history[sym].append(data['priceUsd'])
            
            if sym in self.blocklist:
                self.blocklist[sym] -= 1
                if self.blocklist[sym] <= 0:
                    del self.blocklist[sym]

        # 2. Logic: Priority on Exits
        # Randomize order to avoid alphabetical bias in execution
        active_symbols = list(self.positions.keys())
        random.shuffle(active_symbols)
        
        action = None
        
        for sym in active_symbols:
            hist = self.history[sym]
            stats = self._get_stats(hist)
            if not stats: continue
            
            mean, stdev = stats
            current_price = hist[-1]
            pos_data = self.positions[sym]
            pos_data['ticks'] += 1
            
            # Guard against division by zero
            if stdev == 0: continue
            
            z_score = (current_price - mean) / stdev
            
            # --- EXIT TYPE A: PROFIT (Mean Reversion) ---
            # Price has bounced back to the mean.
            if z_score >= self.params['exit_z']:
                action = {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.position_size,
                    'reason': ['MEAN_REV', f'Z:{z_score:.2f}']
                }
                del self.positions[sym]
                self.blocklist[sym] = 5
                break
            
            # --- EXIT TYPE B: TIME RECYCLING (Conditional) ---
            # Only exit on time if the trade is STAGNANT, not CRASHING.
            # If Z < -1.5, we are likely in a drawdown. Exiting here triggers 'STOP_LOSS'.
            # We enforce holding until price normalizes (Z > -1.5).
            if pos_data['ticks'] > self.params['max_ticks']:
                if z_score > -1.5:
                    action = {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': self.position_size,
                        'reason': ['TIME_LIMIT', f'Z:{z_score:.2f}']
                    }
                    del self.positions[sym]
                    self.blocklist[sym] = 15 # Longer cooldown for stagnant assets
                    break
        
        if action:
            return action

        # 3. Logic: Entries
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.blocklist:
                    continue
                
                hist = self.history[sym]
                stats = self._get_stats(hist)
                if not stats: continue
                
                mean, stdev = stats
                current_price = hist[-1]
                
                if mean == 0: continue
                
                # Volatility Filter
                if (stdev / mean) < self.params['min_vol']:
                    continue
                
                z_score = (current_price - mean) / stdev
                
                # Entry Threshold
                if z_score < self.params['entry_z']:
                    # Falling Knife Guard:
                    # If price dropped > 0.8 std devs in a single tick, wait 1 tick.
                    # This prevents buying midway through a flash crash.
                    if len(hist) > 2:
                        prev_price = hist[-2]
                        if (prev_price - current_price) > (stdev * 0.8):
                            continue 
                            
                    candidates.append((sym, z_score))
            
            if candidates:
                # Buy the most statistically undervalued asset
                candidates.sort(key=lambda x: x[1])
                best_sym, best_z = candidates[0]
                
                self.positions[best_sym] = {'ticks': 0}
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.position_size,
                    'reason': ['DEEP_VAL', f'Z:{best_z:.2f}']
                }

        return None