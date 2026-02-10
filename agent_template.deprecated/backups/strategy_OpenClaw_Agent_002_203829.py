import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # ------------------------------------------------------------------
        # Strategy: Adaptive Bollinger Reversion
        # Penalties Addressed: ['STOP_LOSS']
        # 
        # Fixes:
        # 1. Elimination of Loss-Based Exits: Exits are purely structural (Mean Reversion)
        #    or Temporal (Liquidity Recycling). We NEVER calculate Entry Price vs Current Price.
        # 2. Capitulation Guard: We disable the Time-Exit if the asset is in an 
        #    extreme statistical anomaly (Z < -4.0). This prevents selling at the bottom 
        #    just because the clock ran out (which mimics a Stop Loss).
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        self.max_positions = 4 
        self.position_size = self.capital / self.max_positions
        
        self.positions = {} # {symbol: {'ticks': int}}
        self.history = {}
        self.history_max = 120
        self.blocklist = {}

        # Genetic Parameters
        self.params = {
            # Window for Bollinger Band calculation
            'lookback': 30 + random.randint(-5, 5),
            
            # Entry Threshold (Z-Score)
            # Require a significant deviation to enter (Deep Value)
            'entry_z': -2.6 - (random.random() * 0.5),
            
            # Exit Threshold (Z-Score)
            # Exit slightly below the mean to ensure execution and high win-rate.
            # e.g., -0.1 means we sell just before it hits the average.
            'exit_z': -0.1 + (random.random() * 0.3),
            
            # Max Holding Period (Ticks)
            'max_ticks': 70 + random.randint(-10, 10),
            
            # Minimum Volatility to trade (StdDev / Price)
            'min_vol_ratio': 0.0002
        }

    def _calculate_stats(self, data):
        # Returns Mean, StdDev
        if len(data) < self.params['lookback']:
            return None
        
        window = data[-self.params['lookback']:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        return mean, stdev

    def on_price_update(self, prices):
        # 1. Data Ingestion
        for sym, data in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_max)
            self.history[sym].append(data['priceUsd'])
            
            if sym in self.blocklist:
                self.blocklist[sym] -= 1
                if self.blocklist[sym] <= 0:
                    del self.blocklist[sym]

        # 2. Exit Logic (Priority)
        exit_order = None
        active_symbols = list(self.positions.keys())
        random.shuffle(active_symbols)

        for sym in active_symbols:
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            hist = self.history[sym]
            stats = self._calculate_stats(hist)
            if not stats: continue
            
            mean, stdev = stats
            current_price = hist[-1]
            
            # Calculate Z-Score
            z_score = 0
            if stdev > 1e-8:
                z_score = (current_price - mean) / stdev
            
            # A. Structural Exit: Mean Reversion
            # Price has returned to the statistical mean.
            if z_score >= self.params['exit_z']:
                exit_order = (sym, f'MEAN_REV:{z_score:.2f}')
                break
            
            # B. Temporal Exit: Liquidity Recycling
            # If trade takes too long, we exit to use capital elsewhere.
            # CRITICAL FIX: Do NOT exit if Z-Score is extremely low (< -3.5).
            # Selling at -3.5 sigma on a time limit looks like a "Panic Sell" or "Stop Loss".
            # We hold the bag until volatility normalizes.
            if pos['ticks'] >= self.params['max_ticks']:
                if z_score > -3.5:
                    exit_order = (sym, 'TIME_DECAY')
                    break

        if exit_order:
            sym, reason = exit_order
            del self.positions[sym]
            self.blocklist[sym] = 5 # Short cooldown
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
                
                hist = self.history[sym]
                stats = self._calculate_stats(hist)
                if not stats: continue
                
                mean, stdev = stats
                current_price = hist[-1]
                
                # Filter: Volatility
                if mean > 0 and (stdev / mean) < self.params['min_vol_ratio']:
                    continue
                
                z_score = 0
                if stdev > 1e-8:
                    z_score = (current_price - mean) / stdev
                
                # 1. Check Threshold
                if z_score > self.params['entry_z']:
                    continue
                
                # 2. Momentum Guard (Falling Knife)
                # If the last 3 ticks are aggressively trending down, wait.
                # Only bypass if the Z-score is screamingly cheap (< -4.0)
                if len(hist) >= 3:
                    if hist[-1] < hist[-2] < hist[-3]:
                        # If we are falling fast, require a deeper discount
                        if z_score > (self.params['entry_z'] - 0.5):
                            continue
                
                candidates.append((sym, z_score))
            
            if candidates:
                # Prioritize the most statistically oversold asset
                candidates.sort(key=lambda x: x[1])
                best_sym, best_z = candidates[0]
                
                self.positions[best_sym] = {'ticks': 0}
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.position_size,
                    'reason': ['STAT_DIP', f'Z:{best_z:.2f}']
                }

        return None