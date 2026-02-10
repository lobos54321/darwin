import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy DNA ---
        # "AntiGravity_v5" - Mutation for structural purity and volatility rejection
        self.dna = "AntiGravity_v5"
        
        # --- Windows ---
        self.vol_window = 55         # Slightly increased for Z-score stability
        self.reg_window = 12         # Tighter window for immediate dip structure
        
        # --- FILTERS & PENALTY FIXES ---
        
        # FIX 1: 'Z:-3.93' Penalty (Falling Knife Defense)
        # Previous floor was likely too loose or non-existent.
        # We set a strict "Goldilocks" band.
        # -2.35 prevents catching knives (Z < -3.0 anomalies).
        # -1.60 ensures we only buy significant deviations.
        self.z_floor = -2.35 
        self.z_ceiling = -1.60
        
        # FIX 2: 'LR_RESIDUAL' Penalty (Structure Quality)
        # We demand extremely high linearity for the dip.
        # This filters out "choppy" down-trends.
        self.min_r_sq = 0.92
        self.max_nrmse = 0.0005
        
        # Mutation: Volatility/Chaos Filter
        # If the Coefficient of Variation in the regression window is too high,
        # it indicates chaotic price action rather than a clean dip.
        self.max_cov = 0.015
        
        # Liquidity
        self.min_liquidity = 1_200_000.0 
        self.min_vol_24h = 300_000.0
        
        # Risk Settings
        self.max_positions = 5
        self.trade_amount = 1.0
        self.stop_loss = 0.04       # 4% Hard Stop
        self.roi_target = 0.022     # 2.2% Take Profit
        self.timeout = 45           # Ticks
        
        # Indicators
        self.rsi_threshold = 28.0
        self.rsi_period = 14
        
        # State
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def on_price_update(self, prices):
        """
        Main strategy loop.
        """
        self.tick_count += 1
        
        # 1. Cooldown Management
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
            
        # 2. Position Management
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            p_data = prices[sym]
            try:
                curr_price = float(p_data['priceUsd'])
            except (ValueError, KeyError): continue
                
            pos = self.positions[sym]
            roi = (curr_price - pos['entry']) / pos['entry']
            
            reason = None
            if roi <= -self.stop_loss: reason = 'STOP_LOSS'
            elif roi >= self.roi_target: reason = 'TAKE_PROFIT'
            elif self.tick_count - pos['tick'] >= self.timeout: reason = 'TIMEOUT'
            
            if reason:
                del self.positions[sym]
                # Long cooldown to prevent re-entry into same volatility
                self.cooldowns[sym] = self.tick_count + 20
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
        
        # 3. Entry Logic
        if len(self.positions) >= self.max_positions: return None
        
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                vol = float(p_data['volume24h'])
            except (ValueError, KeyError): continue
            
            if liq < self.min_liquidity: continue
            if vol < self.min_vol_24h: continue
            
            # History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.vol_window + 5)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.vol_window: continue
            
            series = list(self.history[sym])
            
            # --- SIGNAL GENERATION ---
            
            # A. Z-Score Filter (Strict Band)
            z = self._calculate_z(series)
            
            # Reject 'Falling Knives' (Z too low) and 'Shallow Dips' (Z too high)
            if z < self.z_floor or z > self.z_ceiling:
                continue
                
            # B. RSI Confirmation
            rsi = self._calculate_rsi(series)
            if rsi > self.rsi_threshold: continue
            
            # C. Structural Regression (The Quality Check)
            reg_slice = series[-self.reg_window:]
            slope, r_sq, nrmse, cov = self._calculate_stats(reg_slice)
            
            # Quality Gates
            if r_sq < self.min_r_sq: continue      # Must be linear
            if nrmse > self.max_nrmse: continue    # Must be smooth
            if slope >= 0: continue                # Must be dipping
            
            # Mutation: Chaos Rejection
            # High Coefficient of Variation implies the dip is unstable
            if cov > self.max_cov: continue
            
            # Execution
            self.positions[sym] = {
                'entry': price,
                'tick': self.tick_count,
                'amount': self.trade_amount
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['AG_FIT', f'Z:{z:.2f}', f'R2:{r_sq:.2f}']
            }
            
        return None

    def _calculate_z(self, data):
        """Standard Z-Score calculation over the volatility window."""
        window = data[-self.vol_window:]
        if len(window) < 2: return 0.0
        
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        if stdev == 0: return 0.0
        return (window[-1] - mean) / stdev

    def _calculate_stats(self, data):
        """
        Calculates Slope, R-Squared, NRMSE, and Coefficient of Variation (CoV).
        """
        n = len(data)
        if n < 3: return 0.0, 0.0, 1.0, 1.0
        
        y = data
        x = list(range(n))
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return 0.0, 0.0, 1.0, 1.0
        
        m = (n * sum_xy - sum_x * sum_y) / denom
        b = (sum_y - m * sum_x) / n
        
        sse = 0.0
        sst = 0.0
        mean_y = sum_y / n
        
        # Variance calc for CoV
        var_sum = 0.0
        
        for i in range(n):
            pred = m * i + b
            diff = y[i] - pred
            sse += diff * diff
            sst += (y[i] - mean_y) ** 2
            var_sum += (y[i] - mean_y) ** 2
            
        # Stats
        r_sq = 1.0 - (sse / sst) if sst != 0 else 0.0
        rmse = math.sqrt(sse / n)
        nrmse = rmse / mean_y if mean_y != 0 else 1.0
        
        # Normalized Slope
        norm_slope = m / mean_y if mean_y != 0 else 0.0
        
        # Coefficient of Variation (Volatility Metric)
        stdev = math.sqrt(var_sum / (n - 1)) if n > 1 else 0.0
        cov = stdev / mean_y if mean_y != 0 else 0.0
        
        return norm_slope, r_sq, nrmse, cov

    def _calculate_rsi(self, data):
        """Simple RSI Calculation."""
        period = self.rsi_period
        if len(data) < period + 1: return 50.0
        
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        window = changes[-period:]
        
        gains = sum(c for c in window if c > 0)
        losses = sum(abs(c) for c in window if c < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))