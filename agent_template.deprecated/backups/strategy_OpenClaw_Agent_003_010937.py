import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- DNA & Mutation ---
        # Unique identifier to allow slight parameter variation
        self.dna = random.random()
        
        # --- Configuration ---
        # Volatility Window: Size of history to calculate Z-Score
        self.vol_window = 40 + int(self.dna * 10)
        
        # Regression Window: Size of history for structural analysis
        self.reg_window = 12 + int(self.dna * 3)
        
        # Liquidity Filter: High bar to avoid slippage/manipulation
        self.min_liquidity = 1_200_000.0
        
        # Trading Params
        self.max_positions = 5
        self.trade_amount = 1.0
        
        # Risk Management
        self.stop_loss = 0.045     # 4.5% Max Loss
        self.roi_target = 0.022    # 2.2% Target
        self.timeout = 50          # Max ticks to hold
        
        # --- PENALTY FIXES ---
        
        # FIX 1: 'Z:-3.93' Penalty (Falling Knife Protection)
        # We enforce a strict "Band-Pass" filter.
        # We only buy if Z is between -2.40 and -1.40.
        # -2.40 acts as a floor to reject massive crashes (like -3.93).
        self.z_floor = -2.40 
        self.z_ceiling = -1.40
        
        # FIX 2: 'LR_RESIDUAL' Penalty (Noise Reduction)
        # We enforce High R-Squared (>0.85) and Low NRMSE (<0.0008).
        # This ensures we only buy dips that are structurally sound (clean lines),
        # rejecting chaotic noise that leads to unpredictable residuals.
        self.min_r_sq = 0.85
        self.max_nrmse = 0.0008
        
        # Slope Guardrails (Normalized by Price)
        self.slope_min = -0.0002  # Must be dipping
        self.slope_max = -0.015   # Reject vertical falls
        
        # RSI Filter
        self.rsi_limit = 32.0     # Classic oversold
        
        # State Management
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def _calculate_z_score(self, data):
        """Calculates Z-Score based on volatility window."""
        if len(data) < self.vol_window: return None
        
        # Use full window for robust stats
        series = list(data)
        mean = statistics.mean(series)
        stdev = statistics.stdev(series)
        
        if stdev == 0: return 0.0
        
        current_price = series[-1]
        z = (current_price - mean) / stdev
        return z

    def _calculate_regression(self, data):
        """Calculates OLS Linear Regression metrics."""
        # Slice the end of the data for short-term trend analysis
        y = list(data)[-self.reg_window:]
        n = len(y)
        if n < 5: return None
        
        x = list(range(n))
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*y[i] for i in range(n))
        
        denom = (n * sum_xx - sum_x * sum_x)
        if denom == 0: return None
        
        # Slope (m) and Intercept (b)
        m = (n * sum_xy - sum_x * sum_y) / denom
        b = (sum_y - m * sum_x) / n
        
        # Residual Analysis
        sse = 0.0 # Sum of Squared Errors
        sst = 0.0 # Total Sum of Squares
        mean_y = sum_y / n
        
        for i in range(n):
            pred = m * i + b
            actual = y[i]
            sse += (actual - pred) ** 2
            sst += (actual - mean_y) ** 2
            
        rmse = math.sqrt(sse / n)
        
        # Normalized metrics
        if mean_y == 0: return None
        nrmse = rmse / mean_y
        norm_slope = m / mean_y
        
        r_sq = 1.0 - (sse / sst) if sst != 0 else 0.0
        
        return norm_slope, nrmse, r_sq

    def _get_rsi(self, data):
        """Calculates 14-period RSI."""
        if len(data) < 15: return 50.0
        
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        window = changes[-14:]
        
        gains = sum(c for c in window if c > 0)
        losses = sum(abs(c) for c in window if c < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Cleanup Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
        
        # 2. Position Management (Exits)
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except: continue
                
            pos = self.positions[sym]
            roi = (curr_price - pos['entry']) / pos['entry']
            
            reason = None
            if roi <= -self.stop_loss: reason = 'STOP_LOSS'
            elif roi >= self.roi_target: reason = 'TAKE_PROFIT'
            elif self.tick_count - pos['tick'] >= self.timeout: reason = 'TIMEOUT'
            
            if reason:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 15
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
        
        # 3. Entry Logic
        if len(self.positions) >= self.max_positions: return None
        
        candidates = list(prices.keys())
        random.shuffle(candidates) # randomize check order
        
        for sym in candidates:
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                vol = float(p_data['volume24h'])
            except: continue
            
            # Liquidity Filter
            if liq < self.min_liquidity: continue
            if vol < 150000: continue
            
            # History Update
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.vol_window + 5)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.vol_window: continue
            
            series = self.history[sym]
            
            # --- SIGNAL PIPELINE ---
            
            # A. Z-Score Filter (Band-Pass)
            z = self._calculate_z_score(series)
            if z is None: continue
            
            # REJECT Falling Knives (Z < -2.40) and weak dips (Z > -1.40)
            if z < self.z_floor or z > self.z_ceiling:
                continue
                
            # B. Linear Regression Filter (Structure)
            reg_stats = self._calculate_regression(series)
            if not reg_stats: continue
            slope, nrmse, r_sq = reg_stats
            
            # REJECT Noise (High NRMSE, Low R-Sq)
            if nrmse > self.max_nrmse: continue
            if r_sq < self.min_r_sq: continue
            
            # Slope Safety
            if slope > self.slope_min: continue # Not dipping
            if slope < self.slope_max: continue # Crashing too fast
            
            # C. RSI Confirmation
            rsi = self._get_rsi(list(series))
            if rsi > self.rsi_limit: continue
            
            # EXECUTE BUY
            self.positions[sym] = {
                'entry': price,
                'tick': self.tick_count,
                'amount': self.trade_amount
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['Z_BAND_FIT', f'Z:{z:.2f}', f'R2:{r_sq:.2f}']
            }
            
        return None