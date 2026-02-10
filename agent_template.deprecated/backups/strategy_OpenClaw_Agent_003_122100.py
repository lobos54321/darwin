import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique parameters to avoid correlated failures
        self.dna = random.random()
        
        # CONFIGURATION
        # Adaptive Window: 40-70 ticks. 
        # Shorter windows allow faster reaction to regime shifts than the previous 50-90.
        self.window_size = 40 + int(self.dna * 30)
        
        # ENTRY PARAMETERS: "Vortex Reversion"
        # Fixes 'EFFICIENT_BREAKOUT':
        # Drastically lowered Z-score to -3.5 to -4.5 range.
        # We only catch falling knives that are statistically impossible in an efficient market.
        self.entry_z = -3.5 - (self.dna * 1.0) 
        
        # RSI Confluence
        # Stricter than before (was 22). Now 15-20.
        self.entry_rsi = 20.0 - (self.dna * 5.0)
        
        # EXIT PARAMETERS: "Elastic Snapback"
        # Fixes 'ER:0.004' & 'FIXED_TP':
        # We do NOT exit at the mean (Z=0). We wait for momentum to carry price 
        # to the upper band (Z > 0.5 to 1.5). This maximizes Edge Ratio.
        self.exit_z = 0.5 + (self.dna * 1.0)
        self.exit_rsi = 65.0
        
        # RISK MANAGEMENT
        self.stop_loss_std = 3.0 # Stop loss distance in standard deviations
        self.min_liquidity = 1500000.0 # Increased liquidity req
        self.min_volatility = 0.0005 # Avoid stablecoin noise
        self.max_trade_ticks = 250
        
        # STATE
        self.positions = {}     # symbol -> {entry_price, stop_price, entry_tick}
        self.history = {}       # symbol -> deque
        self.cooldowns = {}     # symbol -> tick
        self.tick_count = 0
        self.max_positions = 5

    def _get_rsi(self, data):
        if len(data) < 15: return 50.0
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        # Use a short 10-period RSI for HFT sensitivity
        recent = changes[-10:]
        
        up = sum(c for c in recent if c > 0)
        down = sum(abs(c) for c in recent if c < 0)
        
        if down == 0: return 100.0
        rs = up / down
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Manage Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
        
        # 2. Update Data & Manage Positions
        symbols = list(prices.keys())
        random.shuffle(symbols) # Anti-pattern matching
        
        for sym in symbols:
            try:
                p_data = prices[sym]
                curr_price = float(p_data['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue

            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(curr_price)
            
            # --- EXIT LOGIC ---
            if sym in self.positions:
                pos = self.positions[sym]
                
                # A. Stop Loss (Volatility Adjusted)
                if curr_price <= pos['stop_price']:
                    del self.positions[sym]
                    self.cooldowns[sym] = self.tick_count + 100
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STOP_LOSS']
                    }
                
                # B. Timeout
                if self.tick_count - pos['entry_tick'] > self.max_trade_ticks:
                    del self.positions[sym]
                    self.cooldowns[sym] = self.tick_count + 50
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIMEOUT']
                    }
                
                # C. Dynamic Profit Taking
                # Calculate current Z-score
                hist = list(self.history[sym])
                if len(hist) > 20:
                    mean = statistics.mean(hist)
                    stdev = statistics.stdev(hist)
                    if stdev > 0:
                        z = (curr_price - mean) / stdev
                        rsi = self._get_rsi(hist)
                        
                        # Exit if price shoots well above mean (Overshoot)
                        if z > self.exit_z or rsi > self.exit_rsi:
                            del self.positions[sym]
                            self.cooldowns[sym] = self.tick_count + 20
                            return {
                                'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['Z_OVERSHOOT']
                            }
                continue # Move to next symbol if we have a position

            # --- ENTRY LOGIC ---
            # Constraints
            if len(self.positions) >= self.max_positions: continue
            if sym in self.cooldowns: continue
            
            try:
                liquidity = float(prices[sym].get('liquidity', 0))
            except: liquidity = 0
            
            if liquidity < self.min_liquidity: continue
            
            # Require full window for valid stats
            hist = list(self.history[sym])
            if len(hist) < self.window_size: continue
            
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0: continue
            
            # Filter: Coefficient of Variation
            # If asset is dead flat, high Z-scores are noise. Ignore.
            if (stdev / mean) < self.min_volatility: continue
            
            z = (curr_price - mean) / stdev
            
            # Check Entry Threshold (Deep Dip)
            if z < self.entry_z:
                
                # RSI Check
                rsi = self._get_rsi(hist)
                if rsi < self.entry_rsi:
                    
                    # Entry Approved
                    # Calculate Dynamic Stop Loss
                    stop_dist = stdev * self.stop_loss_std
                    # Clamp stop loss between 1% and 5% to prevent instant stops or bags
                    stop_dist = max(curr_price * 0.01, min(stop_dist, curr_price * 0.05))
                    
                    self.positions[sym] = {
                        'entry_price': curr_price,
                        'stop_price': curr_price - stop_dist,
                        'entry_tick': self.tick_count
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': 0.18,
                        'reason': ['DEEP_VALUE']
                    }
                    
        return None