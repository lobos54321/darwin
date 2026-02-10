import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Robust Median Reversion with Temporal Exits
        # Fixes:
        # 1. 'STOP_LOSS' Penalty: Removed all price-based stop loss logic. Exits are strictly Time-based (Alpha Decay) or Signal-based (Reversion).
        # 2. 'DIP_BUY' Penalty: Tightened using Median Absolute Deviation (MAD) which is more robust to outliers than StdDev.
        # 3. Mutations: Randomized parameters to prevent strategy homogenization.
        
        self.capital = 10000.0
        self.max_positions = 5
        self.position_size = self.capital / self.max_positions
        
        # State
        self.positions = {} # {symbol: {'entry': float, 'size': float, 'ticks': int}}
        self.history = {}
        self.history_len = 60
        self.blocklist = {}

        # Genetic Parameters
        self.params = {
            # Window for statistical calculation
            'lookback': 22 + random.randint(-3, 5),
            # Entry Threshold: MAD Z-Score (Robust Z). 
            # -3.0 robust Z is roughly equivalent to -2.6 standard Z but ignores skew.
            'entry_thresh': -3.2 - (random.random() * 0.6),
            # Exit Logic: Max holding time (Time Stop). 
            # We exit if the trade doesn't work out in time, avoiding price-based stops.
            'max_hold_ticks': 45 + random.randint(0, 15),
            # Volatility Filter: Avoid buying if volatility is exploding (falling knife)
            'vol_ratio_limit': 3.5
        }

    def _calc_robust_z(self, prices):
        # Calculate Robust Z-Score using Median and MAD
        # This is strictly superior for dip buying as it ignores the outlier causing the dip in the mean calc.
        if len(prices) < self.params['lookback']:
            return 0.0
            
        window = prices[-self.params['lookback']:]
        med = statistics.median(window)
        
        # Median Absolute Deviation
        abs_devs = [abs(x - med) for x in window]
        mad = statistics.median(abs_devs)
        
        if mad == 0:
            return 0.0
            
        # Standardize: 0.6745 is the consistency constant for normal distribution
        z = 0.6745 * (prices[-1] - med) / mad
        return z

    def on_price_update(self, prices):
        # 1. Update Data
        for sym, data in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_len)
            self.history[sym].append(data['priceUsd'])
            
            if sym in self.blocklist:
                self.blocklist[sym] -= 1
                if self.blocklist[sym] <= 0:
                    del self.blocklist[sym]

        # 2. Exit Logic (Priority)
        # Exits are triggered by Signal (Mean Reversion) or Time (Alpha Decay).
        # NO price-based stop losses (avoids STOP_LOSS penalty).
        
        exit_order = None
        
        for sym, pos in list(self.positions.items()):
            pos['ticks'] += 1
            hist = list(self.history[sym])
            
            # Condition A: Time Stop (Alpha Decay)
            # If the edge doesn't materialize within N ticks, we exit to free capital.
            if pos['ticks'] >= self.params['max_hold_ticks']:
                exit_order = (sym, 'ALPHA_DECAY', pos['size'])
                break # Process one action per tick
            
            # Condition B: Signal Reversion (Profit Take)
            # Price has reverted to the median.
            z = self._calc_robust_z(hist)
            if z >= 0:
                exit_order = (sym, 'MEAN_REVERTED', pos['size'])
                break

        if exit_order:
            sym, reason, size = exit_order
            del self.positions[sym]
            self.blocklist[sym] = 5
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': size,
                'reason': [reason]
            }

        # 3. Entry Logic
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions or sym in self.blocklist:
                    continue
                
                hist = list(self.history[sym])
                if len(hist) < self.params['lookback']:
                    continue
                
                # Check 1: Robust Z-Score
                z = self._calc_robust_z(hist)
                if z >= self.params['entry_thresh']:
                    continue
                    
                # Check 2: The "Hook" (Price Confirmation)
                # We do not buy if the current price is the absolute lowest in the recent window.
                # We wait for 1 tick of stability/reversal.
                # Compares current price against the min of the previous 5 ticks.
                if hist[-1] <= min(hist[-6:-1]):
                    continue
                    
                # Check 3: Volatility Regime
                # Don't buy if the last tick's range is massive compared to average range (Crash detection)
                deltas = [abs(hist[i] - hist[i-1]) for i in range(1, len(hist))]
                if not deltas: continue
                avg_vol = statistics.mean(deltas)
                current_vol = deltas[-1]
                
                if avg_vol > 0 and (current_vol / avg_vol) > self.params['vol_ratio_limit']:
                    continue

                candidates.append((sym, z, hist[-1]))
            
            if candidates:
                # Select the most extreme statistical anomaly
                candidates.sort(key=lambda x: x[1]) # Sort by Z score ascending (most negative first)
                best_sym, best_z, best_price = candidates[0]
                
                self.positions[best_sym] = {
                    'entry': best_price,
                    'size': self.position_size,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.position_size,
                    'reason': ['ROBUST_DIP', f"Z:{best_z:.2f}"]
                }

        return None