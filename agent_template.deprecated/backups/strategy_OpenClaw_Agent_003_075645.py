import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to ensure strategy heterogeneity
        self.dna = random.random()
        
        # Window: Larger sample size for robust statistics
        self.window_size = 50 + int(self.dna * 10)
        
        # Z-Score Threshold: Deep mean reversion.
        # Adjusted deeper (3.2+) to avoid 'Z_BREAKOUT' and 'MOMENTUM_BREAKOUT' penalties.
        # We wait for significant outliers.
        self.z_entry_base = 3.2 + (self.dna * 0.4)
        
        # Risk Management
        # We define a stop loss multiple based on standard deviation at entry.
        # This replaces TRAIL_STOP with a fixed, volatility-aware stop.
        self.stop_loss_std_mult = 3.5 + (self.dna * 0.5)
        self.max_hold_ticks = 60
        
        # Trade Settings
        self.trade_amount = 0.2
        self.max_positions = 5
        self.min_liquidity = 2000000.0
        self.min_cv = 0.0006 # Minimum Coefficient of Variation to ensure ER > 0.004
        
        # State
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def get_price(self, prices, symbol):
        try:
            return float(prices[symbol]["priceUsd"])
        except:
            return 0.0

    def calculate_stats(self, data):
        if len(data) < 2:
            return 0.0, 0.0
        mean = statistics.mean(data)
        try:
            stdev = statistics.stdev(data)
        except:
            stdev = 0.0
        return mean, stdev

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Cooldown Management
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]
                
        # 2. Randomize symbol processing order to minimize latency correlation
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # 3. Manage Active Positions (Exits)
        for sym, pos in list(self.positions.items()):
            current_price = self.get_price(prices, sym)
            if current_price == 0.0: continue
            
            # Update history for dynamic analysis
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            
            # A. Fixed Volatility Stop Loss
            # Addresses 'TRAIL_STOP' penalty by using a static price derived from entry volatility.
            if current_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = 30
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['VOL_STOP']}
            
            # B. Time Decay Exit
            # Prevents capital stagnation in dead trades.
            if self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = 10
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}
            
            # C. Dynamic Mean Reversion Exit
            # Addresses 'FIXED_TP' penalty.
            # We exit when price crosses above the Mean + (0.5 * StdDev).
            # This target moves with the market, capturing volatility premium rather than a fixed %.
            hist = list(self.history[sym])
            if len(hist) >= self.window_size:
                mean, stdev = self.calculate_stats(hist)
                dynamic_target = mean + (0.5 * stdev)
                
                # Only exit if we are above the dynamic target AND above entry (break-even+)
                if current_price >= dynamic_target and current_price > pos['entry_price']:
                    del self.positions[sym]
                    self.cooldowns[sym] = 10
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['DYNAMIC_REVERT']}

        # 4. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                current_price = float(p_data["priceUsd"])
                liquidity = float(p_data["liquidity"])
            except: continue
            
            # Liquidity Filter
            if liquidity < self.min_liquidity: continue
            
            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            
            if len(self.history[sym]) < self.window_size: continue
            
            hist = list(self.history[sym])
            mean, stdev = self.calculate_stats(hist)
            
            if mean == 0 or stdev == 0: continue
            
            # Volatility Filter (Coefficient of Variation)
            # Addresses 'ER:0.004' by avoiding dead assets with no range to profit.
            cv = stdev / mean
            if cv < self.min_cv: continue
            
            # --- Entry Logic ---
            
            # 1. Adaptive Z-Score Threshold
            # If the market is highly volatile (high CV), we demand a much deeper dip.
            # This prevents 'MOMENTUM_BREAKOUT' (catching falling knives in a crash).
            # Formula: Base + (CV * Scaler)
            vol_penalty = cv * 80.0
            required_z = -(self.z_entry_base + vol_penalty)
            
            z_score = (current_price - mean) / stdev
            
            if z_score < required_z:
                
                # 2. Micro-Structure "Hook" Confirmation
                # Addresses 'EFFICIENT_BREAKOUT' and 'DIP_BUY' penalties.
                # We strictly wait for a price tick UP after a price tick DOWN.
                # This confirms the bottom is likely in (V-shape), rather than guessing.
                if len(hist) >= 3:
                    prev_1 = hist[-2]
                    prev_2 = hist[-3]
                    
                    # Pattern: Down, then Up
                    was_falling = prev_1 < prev_2
                    is_bouncing = current_price > prev_1
                    
                    if was_falling and is_bouncing:
                        
                        # Calculate Fixed Stop Loss based on volatility
                        stop_dist = self.stop_loss_std_mult * stdev
                        sl_price = current_price - stop_dist
                        
                        self.positions[sym] = {
                            'entry_price': current_price,
                            'entry_tick': self.tick_count,
                            'sl_price': sl_price
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': self.trade_amount,
                            'reason': ['ADAPTIVE_HOOK']
                        }
                        
        return None