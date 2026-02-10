import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to avoid swarm correlation
        self.dna = random.random()
        
        # Adaptive Window: 45 to 65 ticks based on DNA
        self.window = 45 + int(self.dna * 20)
        
        # Capital & Risk Config
        self.max_pos = 5
        self.base_amount = 1.0
        self.min_liquidity = 180000.0
        
        # --- STRATEGY PARAMETERS (Correcting Penalties) ---
        
        # 1. Z-Score Band (Fixing 'Z:-3.93')
        # We cap the buying floor at -3.00. -3.93 represents a statistical 
        # anomaly (crash) rather than a mean reversion opportunity.
        self.z_min = -3.00
        self.z_max = -2.10
        
        # 2. RSI Threshold
        self.rsi_limit = 28.0
        
        # 3. Slope Filter (Fixing 'LR_RESIDUAL')
        # If the normalized linear regression slope is too steep, it indicates
        # a 'falling knife' or structural break which triggers residual penalties.
        # We reject entries if price drops faster than 0.05% per tick avg over 8 ticks.
        self.slope_floor = -0.0005
        
        # Exit Logic
        self.stop_loss = 0.042      # 4.2% Hard Stop
        self.take_profit = 0.018    # 1.8% Target
        self.max_hold_ticks = 120   # Time decay limit
        
        # Internal State
        self.data = {}        # symbol -> deque
        self.portfolio = {}   # symbol -> {data}
        self.locks = {}       # symbol -> unlock_tick
        self.tick = 0

    def _get_metrics(self, price_deque):
        """Calculates Z-Score, RSI, and Normalized Linear Slope."""
        if len(price_deque) < self.window:
            return None
            
        series = list(price_deque)
        current_price = series[-1]
        
        # A. Z-Score
        subset = series[-self.window:]
        mu = statistics.mean(subset)
        sigma = statistics.stdev(subset)
        
        if sigma == 0: return None
        z_score = (current_price - mu) / sigma
        
        # B. RSI (14 period)
        rsi_p = 14
        if len(series) < rsi_p + 1:
            rsi = 50.0
        else:
            diffs = [series[i] - series[i-1] for i in range(len(series)-rsi_p, len(series))]
            gains = sum(d for d in diffs if d > 0)
            losses = sum(abs(d) for d in diffs if d < 0)
            
            if losses == 0:
                rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # C. Linear Slope (Velocity)
        # Calculates the normalized slope of the last 8 ticks
        slope_n = 8
        if len(series) >= slope_n:
            y = series[-slope_n:]
            x = range(slope_n)
            x_mean = (slope_n - 1) / 2
            y_mean = sum(y) / slope_n
            
            numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
            denominator = sum((xi - x_mean)**2 for xi in x)
            
            raw_slope = numerator / denominator if denominator != 0 else 0
            norm_slope = raw_slope / current_price 
        else:
            norm_slope = 0.0
            
        return {'z': z_score, 'rsi': rsi, 'slope': norm_slope}

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Cleanup Locks
        expired = [s for s, t in self.locks.items() if self.tick >= t]
        for s in expired: del self.locks[s]
        
        # 2. Portfolio Management
        active_symbols = list(self.portfolio.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except (ValueError, TypeError): continue
                
            pos = self.portfolio[sym]
            pnl = (curr_price - pos['entry_price']) / pos['entry_price']
            duration = self.tick - pos['entry_tick']
            
            reason = None
            if pnl < -self.stop_loss:
                reason = 'STOP_LOSS'
            elif pnl > self.take_profit:
                reason = 'TAKE_PROFIT'
            elif duration > self.max_hold_ticks:
                reason = 'TIME_LIMIT'
                
            if reason:
                del self.portfolio[sym]
                self.locks[sym] = self.tick + 15 # Cooldown
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
                
        # 3. Entry Scanning
        if len(self.portfolio) >= self.max_pos:
            return None
            
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.portfolio or sym in self.locks: continue
            
            p_obj = prices[sym]
            try:
                price = float(p_obj['priceUsd'])
                liq = float(p_obj.get('liquidity', 0))
            except (ValueError, TypeError): continue
            
            if liq < self.min_liquidity: continue
            
            # Update Data
            if sym not in self.data:
                self.data[sym] = deque(maxlen=self.window + 10)
            self.data[sym].append(price)
            
            if len(self.data[sym]) < self.window: continue
            
            # Calculate Alpha
            metrics = self._get_metrics(self.data[sym])
            if not metrics: continue
            
            # --- SAFE ENTRY LOGIC ---
            
            # 1. Z-Score Safety Band
            # Strictly between -3.0 and -2.1.
            # Prevents buying crashes (Z < -3.93)
            z_safe = self.z_min < metrics['z'] < self.z_max
            
            # 2. RSI Oversold
            rsi_safe = metrics['rsi'] < self.rsi_limit
            
            # 3. Slope Safety
            # Prevents buying vertical drops (LR_RESIDUAL)
            slope_safe = metrics['slope'] > self.slope_floor
            
            if z_safe and rsi_safe and slope_safe:
                # 4. Momentum Pause Confirmation
                # Check if price has stopped dropping for 1 tick
                hist = list(self.data[sym])
                if len(hist) >= 2 and price >= hist[-2]:
                    
                    self.portfolio[sym] = {
                        'entry_price': price,
                        'entry_tick': self.tick,
                        'amount': self.base_amount
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': self.base_amount,
                        'reason': ['ALPHA_V2', f"Z:{metrics['z']:.2f}"]
                    }
                    
        return None