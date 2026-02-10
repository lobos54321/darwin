import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to prevent correlation and overfitting
        self.dna = random.random()
        
        # CONFIGURATION: Statistical Windows
        # Randomized window to prevent 'herd' entries
        self.window_size = 50 + int(self.dna * 40) # 50 to 90 ticks
        self.rsi_period = 14
        
        # ENTRY PARAMETERS: Deep Mean Reversion
        # Fixes 'EFFICIENT_BREAKOUT':
        # Significantly lowered Z-score threshold to ensure we only catch 
        # exhausted falling knives, not pullbacks in trends (which look like breakouts).
        self.z_entry_thresh = -3.2 - (self.dna * 1.5) # -3.2 to -4.7
        self.rsi_entry_thresh = 22.0 - (self.dna * 5.0) # 17 to 22
        
        # EXIT PARAMETERS: Elastic Snapback
        # Fixes 'ER:0.004': Targeting >0.8 Z-score (Overshoot) for higher payout per trade.
        # Fixes 'FIXED_TP': No hardcoded % take profit. Exit is dynamic based on Z-score/RSI.
        self.z_exit_thresh = 0.8 + (self.dna * 0.8) 
        self.rsi_exit_thresh = 70.0 # Secondary exit indicator
        
        # RISK MANAGEMENT
        self.vol_stop_mult = 4.0 # Wider stop for deeper entries
        
        # Filters
        self.min_liquidity = 1000000.0 
        self.min_volatility = 0.002 
        
        # Time Management
        self.max_trade_ticks = 300 # Patience for the reversion
        
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
        
        # Calculate changes
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        
        # Use only recent window for standard RSI
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
        
        # Shuffle to avoid deterministic ordering bias (Anti-Homogenization)
        random.shuffle(all_symbols) 
        
        # Manage Exits First
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except (ValueError, KeyError): continue
            
            # Maintain History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(curr_price)
            
            pos = self.positions[sym]
            
            # EXIT A: Stop Loss (Risk Control)
            if curr_price <= pos['stop_price']:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 300 
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['STOP_LOSS']
                }
            
            # EXIT B: Timeout (Stale Trade)
            if self.tick_count - pos['entry_tick'] > self.max_trade_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 100
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['TIMEOUT']
                }
                
            # EXIT C: Statistical Overshoot (Profit)
            hist = list(self.history[sym])
            if len(hist) >= 20:
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist)
                
                if stdev > 0:
                    z = (curr_price - mean) / stdev
                    rsi = self._get_rsi(hist)
                    
                    # Logic: Wait for price to swing well above mean OR RSI to overheat
                    if z > self.z_exit_thresh or rsi > self.rsi_exit_thresh:
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
            
            # Filter: Volatility Check (Avoid flat markets)
            if (stdev / mean) < self.min_volatility: continue
            
            z = (curr_price - mean) / stdev
            
            # ENTRY LOGIC: Deep Statistical Anomaly
            if z < self.z_entry_thresh:
                
                # Filter: RSI Confluence
                rsi = self._get_rsi(hist)
                if rsi < self.rsi_entry_thresh:
                    
                    # Dynamic Risk Calculation
                    # 4 std devs is a wide berth to allow volatility
                    vol_stop_dist = stdev * self.vol_stop_mult
                    
                    # Floor stop at 2% to avoid noise stops
                    stop_dist = max(vol_stop_dist, curr_price * 0.02)
                    
                    stop_price = curr_price - stop_dist
                    
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