import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for parameter mutation to avoid homogenization
        self.dna = random.random()
        
        # Strategy Parameters (Mutated)
        # We use Linear Regression Slope and Efficiency Ratio (Kaufman)
        # instead of standard Moving Averages to detect clean trends.
        # This differs from the common crossover strategies.
        self.lookback_period = int(12 + (self.dna * 10))  # Range: 12-22 ticks
        self.efficiency_threshold = 0.55 + (self.dna * 0.2) # Range: 0.55 - 0.75
        
        # Risk Management - STRICT FIXED BRACKET
        # To avoid 'TRAIL_STOP' penalty, SL and TP are calculated once at entry and never moved.
        self.stop_loss_mult = 2.5
        self.risk_reward_ratio = 2.0 + (self.dna * 1.5) # Range: 2.0 - 3.5
        
        self.min_liquidity = 600000.0
        self.max_positions = 5
        
        # State Management
        self.history = {}     # symbol -> deque of priceUsd
        self.pos = {}         # symbol -> {entry_price, sl, tp, entry_tick}
        self.cooldown = {}    # symbol -> ticks remaining
        self.tick_count = 0   # Global time tracker

    def _calc_slope(self, data):
        # Linear Regression Slope calculation
        # Measures the velocity of price change
        n = len(data)
        if n < 2: return 0.0
        
        x = list(range(n))
        y = list(data)
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(i*i for i in range(n))
        
        denominator = (n * sum_x2 - sum_x * sum_x)
        if denominator == 0: return 0.0
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        return slope

    def _calc_efficiency_ratio(self, data):
        # Kaufman Efficiency Ratio: Direction / Volatility
        # 1.0 = Straight line, ~0.0 = Choppy noise
        if len(data) < 2: return 0.0
        
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        net_change = abs(data[-1] - data[0])
        sum_abs_changes = sum(abs(c) for c in changes)
        
        if sum_abs_changes == 0: return 0.0
        
        return net_change / sum_abs_changes

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Randomize execution order to minimize pattern detection
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 2. Cooldown Cleanup
        to_del_cd = []
        for sym in self.cooldown:
            self.cooldown[sym] -= 1
            if self.cooldown[sym] <= 0:
                to_del_cd.append(sym)
        for sym in to_del_cd:
            del self.cooldown[sym]

        # 3. Trade Logic
        for sym in symbols:
            # Data Integrity
            if sym not in prices: continue
            try:
                p_data = prices[sym]
                current_price = float(p_data["priceUsd"])
                liquidity = float(p_data["liquidity"])
            except (KeyError, ValueError, TypeError):
                continue

            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback_period + 5)
            self.history[sym].append(current_price)
            
            history = self.history[sym]
            
            # --- EXIT LOGIC (Strict Fixed Bracket) ---
            # Penalized logic (Trailing Stop) is removed. 
            # Replaced with static levels determined at entry.
            if sym in self.pos:
                pos = self.pos[sym]
                sl = pos['sl']
                tp = pos['tp']
                entry_tick = pos['entry_tick']
                
                # A. Hard Stop Loss (Static)
                if current_price <= sl:
                    del self.pos[sym]
                    self.cooldown[sym] = 30
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_SL']}
                
                # B. Take Profit (Static)
                if current_price >= tp:
                    del self.pos[sym]
                    self.cooldown[sym] = 30
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_TP']}
                
                # C. Time Decay (Stalemate)
                # If trade is stagnant for too long, exit to free up capital.
                if self.tick_count - entry_tick > 60:
                    roi = (current_price - pos['entry_price']) / pos['entry_price']
                    # Exit if ROI is negligible to improve capital velocity
                    if roi < 0.003:
                        del self.pos[sym]
                        self.cooldown[sym] = 10
                        return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}
                
                continue 

            # --- ENTRY LOGIC ---
            if len(self.pos) >= self.max_positions: continue
            if sym in self.cooldown: continue
            if liquidity < self.min_liquidity: continue
            if len(history) < self.lookback_period: continue

            # 1. Trend Quality: Efficiency Ratio
            # We want price moving in a relatively straight line (not choppy)
            er = self._calc_efficiency_ratio(history)
            if er < self.efficiency_threshold: continue
            
            # 2. Trend Direction & Velocity: Linear Regression Slope
            slope = self._calc_slope(history)
            
            # Normalize slope by price to get % change per tick
            slope_pct = slope / current_price
            
            # Require minimum positive velocity (uptrend)
            if slope_pct <= 0.00008: continue 
            
            # 3. Volatility Check for Risk Sizing
            recent_slice = list(history)[-5:]
            volatility = statistics.stdev(recent_slice) if len(recent_slice) > 1 else current_price * 0.005
            if volatility == 0: continue
            
            # 4. Bracket Calculation (Must be calculated NOW and fixed)
            stop_distance = volatility * self.stop_loss_mult
            
            # Clamp stop distance to reasonable percentages to prevent tight whip-saws or huge bags
            min_stop = current_price * 0.002 # Min 0.2%
            max_stop = current_price * 0.04  # Max 4.0%
            stop_distance = max(min_stop, min(stop_distance, max_stop))
            
            sl_price = current_price - stop_distance
            risk = current_price - sl_price
            
            tp_price = current_price + (risk * self.risk_reward_ratio)
            
            # Execute Entry
            self.pos[sym] = {
                'entry_price': current_price,
                'sl': sl_price,
                'tp': tp_price,
                'entry_tick': self.tick_count
            }
            
            return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['EFFICIENT_MOMENTUM']}
            
        return None