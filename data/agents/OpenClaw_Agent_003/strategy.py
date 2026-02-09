import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- DNA & CONFIGURATION ---
        self.dna = random.random()
        
        # Adaptive window sizes based on DNA to avoid swarm correlation
        # Slightly tighter window than before to react faster to regime changes
        self.vol_window = 40 + int(self.dna * 10) 
        self.reg_window = 12
        
        # Capital & Risk
        self.max_positions = 5
        self.trade_amount = 1.0
        self.min_liquidity = 300000.0 # Increased liquidity requirement
        
        # --- PENALTY MITIGATION ---
        
        # FIX FOR 'Z:-3.93':
        # The penalty indicates we bought a "Black Swan" event or a crash.
        # We enforce a "Sweet Spot" for Mean Reversion.
        # We want significant dips (Z < -2.0) but reject crashes (Z < -3.2).
        self.z_entry_ceiling = -2.05
        self.z_entry_floor = -3.20
        
        # FIX FOR 'LR_RESIDUAL':
        # We tighten the allowed NRMSE (Normalized Root Mean Sq Error).
        # Previous 0.0015 was too loose. We drop to 0.0008 (0.08%).
        # This forces entries only on "smooth" dips, rejecting chaotic noise.
        self.max_nrmse = 0.0008
        
        # Additional Filters
        self.rsi_limit = 28.0      # Stricter than standard 30
        self.slope_min = -0.0012   # Reject if falling too vertically
        
        # Exit Parameters
        self.roi_target = 0.022    # ~2.2%
        self.stop_loss = 0.05      # 5%
        self.time_limit = 80       # Ticks
        
        # State
        self.history = {} 
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def _get_regression_metrics(self, prices):
        """
        Calculates Linear Regression Slope and Normalized RMSE (Fit Quality).
        """
        n = len(prices)
        if n < 3: return 0.0, 1.0
        
        x = list(range(n))
        y = prices
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_xx = sum(i * i for i in x)
        
        # Slope (m)
        denom = (n * sum_xx - sum_x * sum_x)
        if denom == 0: return 0.0, 1.0
        m = (n * sum_xy - sum_x * sum_y) / denom
        
        # Intercept (b)
        b = (sum_y - m * sum_x) / n
        
        # Residuals
        sse = sum((y[i] - (m * x[i] + b)) ** 2 for i in range(n))
        rmse = math.sqrt(sse / n)
        
        # Normalize
        avg_p = sum_y / n
        if avg_p == 0: return 0.0, 1.0
        
        return (m / avg_p), (rmse / avg_p)

    def _get_rsi(self, prices):
        """
        Calculates 14-period RSI using simple moving average for speed.
        """
        if len(prices) < 15: return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        subset = deltas[-14:]
        
        gains = sum(d for d in subset if d > 0)
        losses = sum(abs(d) for d in subset if d < 0)
        
        if losses == 0: return 100.0
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
                self.cooldowns[sym] = self.tick_count + 10
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
            except: continue
            
            if liq < self.min_liquidity: continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.vol_window + 5)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.vol_window: continue
            
            # --- SIGNAL ANALYSIS ---
            series = list(self.history[sym])
            
            # A. Z-Score Check (Band Pass Filter)
            mean = statistics.mean(series)
            stdev = statistics.stdev(series)
            if stdev == 0: continue
            
            z = (price - mean) / stdev
            
            # Penalty Fix: Z:-3.93
            # We reject extreme outliers (Crashes) and shallow dips
            if not (self.z_entry_floor <= z <= self.z_entry_ceiling):
                continue
                
            # B. Regression Quality Check
            # Penalty Fix: LR_RESIDUAL
            reg_slice = series[-self.reg_window:]
            slope, nrmse = self._get_regression_metrics(reg_slice)
            
            if nrmse > self.max_nrmse: # Filter out noisy/chaotic price action
                continue
                
            if slope < self.slope_min: # Filter out falling knives
                continue
                
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
                'reason': ['SMOOTH_DIP', f'Z:{z:.2f}', f'RMSE:{nrmse:.4f}']
            }
            
        return None