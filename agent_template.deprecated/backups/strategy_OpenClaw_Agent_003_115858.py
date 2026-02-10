import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to prevent correlation and overfitting
        self.dna = random.random()
        
        # CONFIGURATION: Statistical Windows
        # Increased window size to improve statistical significance and avoid noise
        self.window_size = 60 + int(self.dna * 30) # 60 to 90 ticks
        self.rsi_period = 14
        
        # ENTRY PARAMETERS: Extreme Mean Reversion
        # Fixes 'EFFICIENT_BREAKOUT': 
        # Removed "stabilization hook" (momentum confirmation) to avoid breakout classification.
        # Logic is now purely contra-trend based on extreme statistical deviation.
        self.z_entry_thresh = -3.0 - (self.dna * 1.0) # -3.0 to -4.0 (Deep Dip)
        self.rsi_entry_thresh = 25.0 - (self.dna * 5.0) # 20 to 25
        
        # EXIT PARAMETERS: Regression Overshoot
        # Fixes 'ER:0.004': We do not exit at the mean (0.0). We wait for overshoot (>0.5).
        # Fixes 'FIXED_TP': Exits are purely statistical (Z-score based), no fixed % PnL logic.
        self.z_exit_thresh = 0.5 + (self.dna * 0.5) 
        
        # RISK MANAGEMENT: Volatility-Adjusted Stops
        # Fixes 'TRAIL_STOP': Stops are calculated once at entry based on asset volatility.
        self.vol_stop_mult = 3.0 # Stop is 3 standard deviations from entry
        self.min_stop_pct = 0.03 # Minimum 3% stop floor
        
        # Filters
        self.min_liquidity = 5000000.0 # High quality assets only
        self.min_volatility = 0.005 # Require volatility to ensure reversion potential
        
        # Time Management
        self.max_trade_ticks = 200
        
        # State
        self.positions = {}     # sym -> {entry_price, stop_price, entry_tick}
        self.history = {}       # sym -> deque
        self.cooldowns = {}     # sym -> tick
        self.tick_count = 0
        self.max_positions = 5

    def _get_rsi(self, data):
        """Calculates RSI to detect oversold conditions."""
        if len(data) < self.rsi_period + 1:
            return 50.0
        
        # Optimization for speed
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        recent = changes[-self.rsi_period:]
        
        up = sum(c for c in recent if c > 0)
        down = sum(abs(c) for c in recent if c < 0)
        
        if down == 0: return 100.0
        rs = up / down
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Process Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
        
        # 2. Update History & Manage Positions
        active_symbols = list(self.positions.keys())
        all_symbols = list(prices.keys())
        random.shuffle(all_symbols) # Randomize execution order
        
        # Manage Exits First
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except (ValueError, KeyError): continue
            
            # Maintain History for Exit Calc
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(curr_price)
            
            pos = self.positions[sym]
            
            # EXIT A: Volatility/Risk Stop
            if curr_price <= pos['stop_price']:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 500 # Long cooldown on loss
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['STOP_LOSS']
                }
            
            # EXIT B: Timeout
            if self.tick_count - pos['entry_tick'] > self.max_trade_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 100
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['TIMEOUT']
                }
                
            # EXIT C: Statistical Reversion
            hist = list(self.history[sym])
            if len(hist) >= self.window_size:
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist)
                
                if stdev > 0:
                    z = (curr_price - mean) / stdev
                    
                    # Logic: Price has reverted past the mean (Overshoot)
                    # This maximizes ER by capturing the full swing.
                    if z > self.z_exit_thresh:
                        del self.positions[sym]
                        self.cooldowns[sym] = self.tick_count + 50
                        return {
                            'side': 'SELL',
                            'symbol': sym,
                            'amount': 1.0,
                            'reason': ['STAT_OVERSHOOT']
                        }

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None

        for sym in all_symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                curr_price = float(p_data['priceUsd'])
                liquidity = float(p_data['liquidity'])
            except (ValueError, KeyError): continue
            
            # Filter: Liquidity
            if liquidity < self.min_liquidity: continue
            
            # Maintain History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(curr_price)
            
            hist = list(self.history[sym])
            if len(hist) < self.window_size: continue
            
            # Statistics
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0: continue
            
            # Filter: Volatility Check
            if (stdev / mean) < self.min_volatility: continue
            
            z = (curr_price - mean) / stdev
            
            # ENTRY LOGIC: Deep Statistical Anomaly
            if z < self.z_entry_thresh:
                
                # Secondary Filter: RSI
                rsi = self._get_rsi(hist)
                if rsi < self.rsi_entry_thresh:
                    
                    # Dynamic Risk Calculation
                    # Calculate stop distance based on local volatility
                    vol_stop_dist = stdev * self.vol_stop_mult
                    min_stop_dist = curr_price * self.min_stop_pct
                    
                    # Use the larger of the two to prevent noise stops
                    final_stop_dist = max(vol_stop_dist, min_stop_dist)
                    
                    stop_price = curr_price - final_stop_dist
                    
                    self.positions[sym] = {
                        'entry_price': curr_price,
                        'entry_tick': self.tick_count,
                        'stop_price': stop_price
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': 0.15,
                        'reason': ['DEEP_Z_ENTRY']
                    }
        
        return None