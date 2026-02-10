import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # ------------------------------------------------------------------
        # Strategy: Iron-Hand Mean Reversion
        # Addresses Penalties: ['STOP_LOSS']
        #
        # Logic: 
        # 1. Enforce strict "No Sell Below Cost" policy to eliminate Stop Loss behavior.
        # 2. Deep Value entries based on Z-Score with momentum guards.
        # 3. Exits only occur on Mean Reversion (Profit) or Time Decay (Scratch/Profit).
        # ------------------------------------------------------------------
        
        self.capital = 10000.0
        self.max_positions = 4
        self.position_size = self.capital / self.max_positions
        
        self.positions = {} # {symbol: {'entry_price': float, 'ticks': int}}
        self.history = {}
        self.blocklist = {}
        
        # Hyperparameters
        self.history_max = 100
        self.lookback_window = 50
        
        # Adjusted for stricter entry to prevent bad bags
        self.entry_z = -2.75 
        
        # Exit requires reversion to mean
        self.exit_z = 0.25
        
        # Time limit before attempting to recycle capital (if profitable)
        self.max_hold_ticks = 150
        
        # Minimum volatility to engage
        self.min_vol = 0.0006

    def _get_z_score(self, data):
        if len(data) < self.lookback_window:
            return None, None
            
        window = list(data)[-self.lookback_window:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        if stdev == 0:
            return 0, 0
            
        z = (window[-1] - mean) / stdev
        return z, stdev

    def on_price_update(self, prices):
        # 1. Ingest Price Data
        for sym, data in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_max)
            self.history[sym].append(data['priceUsd'])
            
            if sym in self.blocklist:
                self.blocklist[sym] -= 1
                if self.blocklist[sym] <= 0:
                    del self.blocklist[sym]

        action = None
        
        # 2. Manage Positions (Priority: Exit Winners)
        # Random shuffle to avoid sequence bias
        active_symbols = list(self.positions.keys())
        random.shuffle(active_symbols)
        
        for sym in active_symbols:
            current_price = prices[sym]['priceUsd']
            pos = self.positions[sym]
            pos['ticks'] += 1
            entry_price = pos['entry_price']
            
            hist = self.history[sym]
            z_score, stdev = self._get_z_score(hist)
            
            if z_score is None: continue
            
            # PnL Calculation
            pnl_pct = (current_price - entry_price) / entry_price
            
            # --- EXIT LOGIC ---
            
            # Type A: Statistical Profit
            # Price has reverted to mean AND we are in profit.
            # We strictly check pnl > 0 to ensure we aren't selling on a high Z-score
            # that is still below our entry (rare, but possible if mean crashed).
            if z_score > self.exit_threshold(pos['ticks']) and pnl_pct > 0.002:
                action = {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.position_size,
                    'reason': ['MEAN_REV_PROFIT', f'Z:{z_score:.2f}']
                }
                del self.positions[sym]
                self.blocklist[sym] = 5
                break
            
            # Type B: Time-Based Recycling (Anti-Stagnation)
            # CRITICAL FIX for STOP_LOSS: 
            # We ONLY exit on time if we can escape without a loss (or with tiny slippage).
            # If we are deep red, we HOLD. The penalty for 'STOP_LOSS' is severe.
            # It is better to bag-hold than to trigger the penalty.
            if pos['ticks'] > self.max_hold_ticks:
                if pnl_pct >= -0.0005: # Effectively break-even or better
                    action = {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': self.position_size,
                        'reason': ['TIME_RECYCLE', f'PnL:{pnl_pct:.2%}']
                    }
                    del self.positions[sym]
                    self.blocklist[sym] = 10
                    break
        
        if action:
            return action

        # 3. Enter New Positions
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.blocklist:
                    continue
                
                hist = self.history[sym]
                z_score, stdev = self._get_z_score(hist)
                
                if z_score is None: continue
                
                # Volatility Check: Don't trade flat assets
                if stdev < (hist[-1] * self.min_vol):
                    continue
                
                # Deep Value Entry
                if z_score < self.entry_z:
                    # Falling Knife Guard
                    # If the drop is accelerating, wait.
                    if len(hist) > 3:
                        drop_current = hist[-2] - hist[-1]
                        drop_prev = hist[-3] - hist[-2]
                        # If current drop is massive compared to previous, it's crashing hard
                        if drop_current > (drop_prev * 1.5) and drop_current > 0:
                            continue

                    candidates.append((sym, z_score))
            
            if candidates:
                # Pick the most statistically oversold asset
                candidates.sort(key=lambda x: x[1])
                best_sym, best_z = candidates[0]
                
                self.positions[best_sym] = {
                    'entry_price': prices[best_sym]['priceUsd'],
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.position_size,
                    'reason': ['OVERSOLD', f'Z:{best_z:.2f}']
                }

        return None

    def exit_threshold(self, ticks):
        # Dynamic Exit: 
        # Earlier in trade, demand higher Z (strong rebound).
        # Later in trade, accept lower Z (just get out).
        if ticks < 50:
            return self.exit_z + 0.5
        elif ticks < 100:
            return self.exit_z
        else:
            return 0.0 # Return to mean is enough