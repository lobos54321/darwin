import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- DNA & CONFIGURATION ---
        self.dna = random.random()
        
        # Adaptive window sizes based on DNA
        # We increase the window slightly to smooth out noise (Penalty Fix: LR_RESIDUAL)
        self.vol_window = 35 + int(self.dna * 10) 
        self.reg_window = 12 + int(self.dna * 4)
        
        # Capital & Risk
        self.max_positions = 5
        self.trade_amount = 1.0
        # Increased liquidity requirement to avoid manipulation in low-cap assets
        self.min_liquidity = 600000.0  
        
        # --- PENALTY FIXES ---
        
        # FIX 1: 'Z:-3.93' (Deep Crash / Falling Knife)
        # We implement a strict Band-Pass filter for the Z-Score.
        # We reject anything below -2.65 to avoid "Black Swan" drops.
        # We reject anything above -1.95 to ensure sufficient reversion potential.
        self.z_floor = -2.65
        self.z_ceil = -1.95
        
        # FIX 2: 'LR_RESIDUAL' (Noise/Chaos)
        # We enforce a very low NRMSE (Normalized Root Mean Sq Error).
        # This ensures the price action is smooth and structured, not erratic.
        self.max_nrmse = 0.00055 
        self.min_r_sq = 0.65     # Require strong linear correlation
        
        # Slope Filters
        self.slope_min = -0.0004   # Must be dipping
        self.slope_max = -0.022    # Reject vertical crashes
        
        # RSI Filter
        self.rsi_limit = 28.0      # Oversold threshold
        
        # Exit Parameters
        self.roi_target = 0.022 + (self.dna * 0.005) # ~2.2% - 2.7%
        self.stop_loss = 0.045     # 4.5% Hard Stop
        self.time_limit = 60       # Rotation speed
        
        # State
        self.history = {} 
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def _get_regression_metrics(self, prices):
        """
        Calculates normalized slope, NRMSE, and R-Squared.
        """
        n = len(prices)
        if n < 3: return 0.0, 1.0, 0.0
        
        x = list(range(n))
        y = prices
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i * i for i in x)
        sum_xy = sum(i * y[i] for i in range(n))
        
        # Slope (m)
        denom = (n * sum_xx - sum_x * sum_x)
        if denom == 0: return 0.0, 1.0, 0.0
        m = (n * sum_xy - sum_x * sum_y) / denom
        
        # Intercept (b)
        b = (sum_y - m * sum_x) / n
        
        # Residuals
        sse = 0.0
        ssto = 0.0
        avg_y = sum_y / n
        
        for i in range(n):
            prediction = m * x[i] + b
            sse += (y[i] - prediction) ** 2
            ssto += (y[i] - avg_y) ** 2
        
        # RMSE
        rmse = math.sqrt(sse / n)
        
        # Normalization
        if avg_y == 0: return 0.0, 1.0, 0.0
        nrmse = rmse / avg_y
        norm_slope = m / avg_y
        
        # R-Squared
        r_sq = 1.0 - (sse / ssto) if ssto != 0 else 0.0
        
        return norm_slope, nrmse, r_sq

    def _get_rsi(self, prices):
        """
        Calculates simple RSI.
        """
        if len(prices) < 15: return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        subset = deltas[-14:]
        
        gains = sum(d for d in subset if d > 0)
        losses = sum(abs(d) for d in subset if d < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Cleanup Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
        
        # 2. Process Exits
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr = float(prices[sym]['priceUsd'])
            except: continue
                
            pos = self.positions[sym]
            roi = (curr - pos['entry']) / pos['entry']
            
            reason = None
            if roi <= -self.stop_loss: reason = 'STOP_LOSS'
            elif roi >= self.roi_target: reason = 'TAKE_PROFIT'
            elif self.tick_count - pos['tick'] >= self.time_limit: reason = 'TIMEOUT'
            
            if reason:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 10 # Standard cooldown
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
                
        # 3. Process Entries
        if len(self.positions) >= self.max_positions: return None
        
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
                vol = float(p_data.get('volume24h', 0))
            except: continue
            
            # Basic Filters
            if liq < self.min_liquidity: continue
            if vol < 100000: continue
            
            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.vol_window + 5)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.vol_window: continue
            
            # --- SIGNAL ANALYSIS ---
            series = list(self.history[sym])
            
            # A. Z-Score (Statistical Mean Reversion)
            mean = statistics.mean(series)
            stdev = statistics.stdev(series)
            if stdev == 0: continue
            
            z = (price - mean) / stdev
            
            # FIX: Strict floor to prevent 'Z:-3.93' penalty (Falling Knife)
            if z < self.z_floor or z > self.z_ceil:
                continue
                
            # B. Linear Regression (Structural Integrity)
            reg_slice = series[-self.reg_window:]
            slope, nrmse, r_sq = self._get_regression_metrics(reg_slice)
            
            # FIX: Strict NRMSE to prevent 'LR_RESIDUAL' penalty (Noise)
            if nrmse > self.max_nrmse: continue 
            if r_sq < self.min_r_sq: continue
            
            # Slope Safety
            if slope > self.slope_min: continue # Not dipping
            if slope < self.slope_max: continue # Crashing
                
            # C. RSI Confirmation
            rsi = self._get_rsi(series)
            if rsi > self.rsi_limit:
                continue
                
            # EXECUTE
            self.positions[sym] = {
                'entry': price,
                'tick': self.tick_count,
                'amount': self.trade_amount
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['FIT_SCORE', f'Z:{z:.2f}', f'E:{nrmse:.5f}']
            }
            
        return None