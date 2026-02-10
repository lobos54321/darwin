import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- DNA & CONFIGURATION ---
        self.dna = random.random()
        
        # Adaptive window sizes based on DNA to avoid swarm correlation
        # Shorter volatility window for faster adaptation to regime changes
        self.vol_window = 30 + int(self.dna * 15) 
        self.reg_window = 10 + int(self.dna * 5)
        
        # Capital & Risk
        self.max_positions = 5
        self.trade_amount = 1.0
        self.min_liquidity = 500000.0  # Increased to filter low-cap noise/manipulation
        
        # --- PENALTY MITIGATION & FIXES ---
        
        # FIX FOR 'Z:-3.93' (Deep Crash / Falling Knife):
        # The penalty implies we bought a statistical outlier (3.93 sigmas down).
        # We raise the floor significantly to reject these "Black Swan" events.
        # We only want to buy the "Sweet Spot" of mean reversion.
        self.z_entry_floor = -2.75 
        self.z_entry_ceiling = -1.90
        
        # FIX FOR 'LR_RESIDUAL' (Noise/Chaos):
        # We tighten the allowed NRMSE (Normalized Root Mean Sq Error) to 0.0006.
        # We also enforce a minimum R-Squared to ensure the dip has linear structure.
        self.max_nrmse = 0.0006
        self.min_r_sq = 0.60
        
        # Additional Filters
        self.rsi_limit = 26.0      # Very oversold only
        self.slope_min = -0.0005   # Must be dipping (negative slope)
        self.slope_max = -0.025    # Reject if falling vertically (Crash protection)
        
        # Exit Parameters
        self.roi_target = 0.021 + (self.dna * 0.004) # ~2.1% - 2.5%
        self.stop_loss = 0.04      # 4% Hard Stop
        self.time_limit = 65       # Faster rotation
        
        # State
        self.history = {} 
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def _get_regression_metrics(self, prices):
        """
        Calculates Linear Regression Slope, NRMSE, and R-Squared.
        """
        n = len(prices)
        if n < 3: return 0.0, 1.0, 0.0
        
        x = list(range(n))
        y = prices
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_xx = sum(i * i for i in x)
        
        # Slope (m)
        denom = (n * sum_xx - sum_x * sum_x)
        if denom == 0: return 0.0, 1.0, 0.0
        m = (n * sum_xy - sum_x * sum_y) / denom
        
        # Intercept (b)
        b = (sum_y - m * sum_x) / n
        
        # Residuals & SSTO (Total Sum of Squares)
        avg_y = sum_y / n
        sse = 0.0
        ssto = 0.0
        
        for i in range(n):
            prediction = m * x[i] + b
            sse += (y[i] - prediction) ** 2
            ssto += (y[i] - avg_y) ** 2
        
        # RMSE
        rmse = math.sqrt(sse / n)
        
        # Normalize RMSE
        if avg_y == 0: return 0.0, 1.0, 0.0
        nrmse = rmse / avg_y
        
        # R-Squared
        if ssto == 0: r_sq = 1.0 # Flat line
        else: r_sq = 1.0 - (sse / ssto)
        
        return (m / avg_y), nrmse, r_sq

    def _get_rsi(self, prices):
        """
        Calculates 14-period RSI.
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
        
        # 2. Exits
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
                self.cooldowns[sym] = self.tick_count + 15 # Extended cooldown
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
                
        # 3. Entries
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
            
            if liq < self.min_liquidity: continue
            if vol < 100000: continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.vol_window + 5)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.vol_window: continue
            
            # --- SIGNAL ANALYSIS ---
            series = list(self.history[sym])
            
            # A. Z-Score (Band Pass Filter)
            mean = statistics.mean(series)
            stdev = statistics.stdev(series)
            if stdev == 0: continue
            
            z = (price - mean) / stdev
            
            # FIX 1: Strict rejection of Z < -2.75 to solve 'Z:-3.93' penalty
            if z < self.z_entry_floor or z > self.z_entry_ceiling:
                continue
                
            # B. Regression Quality Check
            reg_slice = series[-self.reg_window:]
            slope, nrmse, r_sq = self._get_regression_metrics(reg_slice)
            
            # FIX 2: Strict Residual and Structure checks to solve 'LR_RESIDUAL'
            if nrmse > self.max_nrmse: continue # Reject noisy price action
            if r_sq < self.min_r_sq: continue   # Reject dips lacking linear structure
            
            # Filter Falling Knives
            if slope > self.slope_min: continue # Not dipping
            if slope < self.slope_max: continue # Dipping too fast (Crash)
                
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
                'reason': ['FIT_DIP', f'Z:{z:.2f}', f'E:{nrmse:.5f}']
            }
            
        return None