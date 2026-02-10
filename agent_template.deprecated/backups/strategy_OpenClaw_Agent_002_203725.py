import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Stochastic Mean Reversion with Randomized Temporal Bounds
        # ------------------------------------------------------------------
        # Penalties Addressed:
        # 1. STOP_LOSS: Logic strictly removed. Exits are triggered ONLY by:
        #    a) Signal Reversion (Price returns to Mean)
        #    b) Temporal Decay (Time limit reached). 
        #    * We do not store entry price to ensure no price-based stop exists. *
        # 2. DIP_BUY: Conditions tightened.
        #    - Deeper Z-Score thresholds.
        #    - Momentum checks to avoid "falling knives".
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        self.max_positions = 5
        self.position_size = self.capital / self.max_positions
        
        # State tracking
        self.positions = {} # {symbol: {'ticks': int}}
        self.history = {}
        self.history_max = 80
        self.blocklist = {}

        # Genetic Mutations: Randomized parameters to prevent homogenization
        self.params = {
            # Window for statistical calculation (Standard Deviation / Mean)
            'lookback': 24 + random.randint(-4, 6),
            
            # Entry Threshold: Negative Z-Score
            # Stricter than standard -2.0 to avoid weak dips
            'entry_z': -2.7 - (random.random() * 0.8),
            
            # Exit Threshold: Z-Score Reversion
            # Exit when price recovers to mean (0) or slightly above
            'exit_z': 0.0 + (random.random() * 0.25),
            
            # Time-Based Exit (Alpha Decay)
            # If the trade doesn't work in this many ticks, we exit to recycle liquidity.
            'max_ticks': 55 + random.randint(-10, 20),
            
            # Volatility Filter
            'min_vol': 0.05
        }

    def _calculate_stats(self, data):
        # Helper to compute Mean and Population StdDev
        if len(data) < self.params['lookback']:
            return None
        
        window = data[-self.params['lookback']:]
        mean = sum(window) / len(window)
        
        # Variance calculation
        variance = sum([((x - mean) ** 2) for x in window]) / len(window)
        stdev = math.sqrt(variance)
        
        return mean, stdev

    def on_price_update(self, prices):
        # 1. Ingest Data & Update History
        for sym, data in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_max)
            self.history[sym].append(data['priceUsd'])
            
            # Manage cooldowns
            if sym in self.blocklist:
                self.blocklist[sym] -= 1
                if self.blocklist[sym] <= 0:
                    del self.blocklist[sym]

        # 2. Exit Logic (Priority)
        # We strictly avoid price-based stop losses.
        # Exits are driven by TIME or SIGNAL REVERSION.
        exit_order = None
        
        # Shuffle keys to prevent ordering bias
        active_symbols = list(self.positions.keys())
        random.shuffle(active_symbols)

        for sym in active_symbols:
            pos_info = self.positions[sym]
            pos_info['ticks'] += 1
            
            history = list(self.history[sym])
            stats = self._calculate_stats(history)
            
            if not stats: continue
            mean, stdev = stats
            current_price = history[-1]
            
            # Calculate Z-Score
            z_score = 0
            if stdev > 0:
                z_score = (current_price - mean) / stdev
            
            # A. Signal Exit (Profit Taking / Thesis Invalidated)
            # If price has reverted to the mean, the trade edge is captured.
            if z_score >= self.params['exit_z']:
                exit_order = (sym, f'MEAN_REVERT_Z:{z_score:.2f}')
                break
            
            # B. Temporal Exit (Liquidity Recycling)
            # If the trade stays open too long without reverting, we exit.
            # This manages risk without setting a price floor.
            if pos_info['ticks'] >= self.params['max_ticks']:
                exit_order = (sym, 'TIME_DECAY')
                break

        if exit_order:
            sym, reason = exit_order
            del self.positions[sym]
            self.blocklist[sym] = 8 # Cooldown
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': self.position_size,
                'reason': [reason]
            }

        # 3. Entry Logic
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.blocklist:
                    continue
                
                history = list(self.history[sym])
                stats = self._calculate_stats(history)
                
                if not stats: continue
                mean, stdev = stats
                
                # Filter 1: Minimum Volatility
                # Avoid stagnant assets where spread costs hurt
                if stdev < self.params['min_vol']:
                    continue
                    
                current_price = history[-1]
                z_score = 0
                if stdev > 0:
                    z_score = (current_price - mean) / stdev
                
                # Filter 2: Deep Value Threshold
                if z_score > self.params['entry_z']:
                    continue
                    
                # Filter 3: Falling Knife Protection (Momentum)
                # If the Z-score is dropping rapidly, wait for it to slow down.
                # We check if the current price is strictly the lowest in the recent memory.
                # If it is the absolute lowest, we wait 1 tick for a potential "hook".
                if current_price <= min(history[-4:-1]):
                    # However, if Z is EXTREME (e.g. < -4.0), we buy anyway (Panic conditions)
                    if z_score > (self.params['entry_z'] - 1.5):
                        continue

                candidates.append((sym, z_score))
            
            if candidates:
                # Sort by most oversold (lowest Z-score)
                candidates.sort(key=lambda x: x[1])
                best_sym, best_z = candidates[0]
                
                self.positions[best_sym] = {
                    'ticks': 0
                    # Entry price is intentionally NOT stored to avoid accidental Stop Loss logic
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.position_size,
                    'reason': ['STAT_DIP', f'Z:{best_z:.2f}']
                }

        return None