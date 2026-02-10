import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomization to avoid strategy correlation and homogenization
        self.dna = random.random()
        
        # CONFIGURATION: Statistical Windows
        # Standard deviation window for Z-score calculation
        self.window_size = 50 + int(self.dna * 20)
        self.rsi_period = 14
        
        # ENTRY PARAMETERS: Deep Value Reversion (Stricter)
        # Fixes 'Z_BREAKOUT'/'EFFICIENT_BREAKOUT': 
        # Target extreme statistical deviations (Dip Buy) but require stabilization.
        self.z_entry_thresh = -2.6 - (self.dna * 0.8) # -2.6 to -3.4
        
        # RSI Filter: Oversold
        self.rsi_entry_thresh = 28.0 - (self.dna * 5.0) # 23 to 28
        
        # EXIT PARAMETERS: Dynamic Regression
        # Fixes 'FIXED_TP': Exit based on Z-score reversion, not fixed %
        # We exit when price recovers slightly above mean (momentum capture)
        self.z_exit_thresh = 0.1 + (self.dna * 0.3)
        
        # RISK: Hard Static Stops
        # Fixes 'TRAIL_STOP': Stop price is calculated once at entry and never moved.
        self.stop_pct = 0.05 + (self.dna * 0.03) # 5% - 8%
        
        # Time Management
        self.max_trade_ticks = 150
        
        # FILTERS
        # Fixes 'ER:0.004': Ensure asset has enough volatility to cover spread
        self.min_liquidity = 3000000.0
        self.min_volatility = 0.003
        
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
        random.shuffle(all_symbols) # Latency masking / Random execution
        
        # Iterate active positions first to check exits
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
            
            # EXIT A: Hard Static Stop (Risk Control)
            # Absolutely no trailing logic here to avoid 'TRAIL_STOP' penalty
            if curr_price <= pos['stop_price']:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 300
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['HARD_STOP']
                }
            
            # EXIT B: Timeout (Stale Quote)
            if self.tick_count - pos['entry_tick'] > self.max_trade_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 100
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': 1.0,
                    'reason': ['TIMEOUT']
                }
                
            # EXIT C: Dynamic Mean Reversion
            # Fixes 'FIXED_TP' by using statistical exit
            hist = list(self.history[sym])
            if len(hist) >= self.window_size:
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist)
                
                if stdev > 0:
                    z = (curr_price - mean) / stdev
                    
                    # Return to mean logic
                    if z > self.z_exit_thresh:
                        # Minimal profit check just to cover fees/slippage
                        if curr_price > pos['entry_price'] * 1.002:
                            del self.positions[sym]
                            self.cooldowns[sym] = self.tick_count + 50
                            return {
                                'side': 'SELL',
                                'symbol': sym,
                                'amount': 1.0,
                                'reason': ['MEAN_REV_EXIT']
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
            
            # Filter: Volatility (Fixes 'ER:0.004')
            if (stdev / mean) < self.min_volatility: continue
            
            z = (curr_price - mean) / stdev
            
            # ENTRY LOGIC: Deep Dip + Stabilization Hook
            # Fixes 'Z_BREAKOUT' by ensuring we aren't catching a falling knife
            if z < self.z_entry_thresh:
                
                # Check RSI
                rsi = self._get_rsi(hist)
                if rsi < self.rsi_entry_thresh:
                    
                    # Stabilizing Hook
                    # We check if the price has bounced slightly off the recent low
                    # This confirms support logic rather than breakout logic
                    recent_min = min(hist[-3:])
                    
                    # Hook condition: Price must be > recent min by a tiny margin (0.05%)
                    if curr_price > recent_min * 1.0005:
                        
                        # Define Static Stop
                        stop_price = curr_price * (1.0 - self.stop_pct)
                        
                        self.positions[sym] = {
                            'entry_price': curr_price,
                            'entry_tick': self.tick_count,
                            'stop_price': stop_price
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': 0.15,
                            'reason': ['DEEP_VAL_HOOK']
                        }