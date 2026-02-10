import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy DNA ---
        # "AntiGravity_v6_Flux"
        # Adjusted for strict penalty evasion (LR_RESIDUAL, Z-SCORE)
        self.dna = "AntiGravity_v6_Flux"
        
        # --- Observation Windows ---
        self.vol_window = 50         # Standard window for Z-Score statistical relevance
        self.reg_window = 14         # Tight window to assess dip structure quality
        
        # --- PENALTY FIXES & FILTERS ---
        
        # FIX 1: 'Z:-3.93' Penalty (Falling Knife Defense)
        # The penalty implies we bought too deep into a crash.
        # We enforce a "Goldilocks Zone":
        # - Floor at -2.40 prevents buying falling knives (Z < -3.0).
        # - Ceiling at -1.65 ensures we don't buy shallow noise.
        self.z_floor = -2.40
        self.z_ceiling = -1.65
        
        # FIX 2: 'LR_RESIDUAL' Penalty (Structure Quality)
        # The penalty suggests the dip wasn't clean/linear enough.
        # We increase R-Squared requirement and enforce tight Standard Error.
        self.min_r_sq = 0.93          # Extremely high linearity required
        self.max_std_err = 0.0004     # Max normalized standard error (0.04%)
        
        # RSI Filter
        # Stricter threshold to ensure deep oversold conditions before structural check.
        self.rsi_threshold = 26.0
        self.rsi_period = 14
        
        # Volatility Filter
        # Reject chaotic price action using Coefficient of Variation (CoV)
        self.max_cov = 0.012
        
        # Liquidity & Volume Gates
        # Filter out thin order books
        self.min_liquidity = 1_500_000.0 
        self.min_vol_24h = 500_000.0
        
        # Risk Management Settings
        self.max_positions = 5
        self.trade_amount = 1.0
        self.stop_loss = 0.035       # 3.5% Stop Loss
        self.roi_target = 0.021      # 2.1% Take Profit
        self.timeout = 40            # 40 Ticks Timeout
        
        # State
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def on_price_update(self, prices):
        """
        Core strategy loop executed on every tick.
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
                # Cooldown to prevent re-entering a completed trade immediately
                self.cooldowns[sym] = self.tick_count + 15
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
        
        # 3. Entry Scanning
        if len(self.positions) >= self.max_positions: return None
        
        candidates = list(prices.keys())
        random.shuffle(candidates) # Randomized scan order
        
        for sym in candidates:
            # Filters: Active, Cooldown, Data Validity
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                vol = float(p_data['volume24h'])
            except (ValueError, KeyError): continue
            
            if liq < self.min_liquidity: continue
            if vol < self.min_vol_24h: continue
            
            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.vol_window + 5)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.vol_window: continue
            
            series = list(self.history[sym])
            
            # --- SIGNAL GENERATION ---
            
            # A. Z-Score Filter (The "Goldilocks" Band)
            # We strictly enforce the floor to avoid the Z:-3.93 penalty.
            z = self._calculate_z(series)
            if z < self.z_floor or z > self.z_ceiling:
                continue
                
            # B. RSI Confirmation
            rsi = self._calculate_rsi(series)
            if rsi > self.rsi_threshold: continue
            
            # C. Structural Regression (The Quality Check)
            # This fixes 'LR_RESIDUAL'. We demand a smooth linear dip.
            reg_slice = series[-self.reg_window:]
            slope, r_sq, std_err = self._calculate_regression_stats(reg_slice)
            
            # 1. Linearity Gate
            if r_sq < self.min_r_sq: continue
            
            # 2. Residual Error Gate (Smoothness)
            if std_err > self.max_std_err: continue
            
            # 3. Direction Gate
            if slope >= 0: continue
            
            # D. Volatility / Chaos Gate
            # If the dip is too chaotic (high coefficient of variation), skip.
            cov = self._calculate_cov(reg_slice)
            if cov > self.max_cov: continue
            
            # --- EXECUTION ---
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
        """Standard Z-Score calculation."""
        window = data[-self.vol_window:]
        if len(window) < 2: return 0.0
        
        try:
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
        except: return 0.0
        
        if stdev == 0: return 0.0
        return (window[-1] - mean) / stdev

    def _calculate_regression_stats(self, data):
        """
        Calculates normalized Slope, R-Squared, and normalized Standard Error.
        """
        n = len(data)
        if n < 3: return 0.0, 0.0, 1.0
        
        x = list(range(n))
        y = data
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return 0.0, 0.0, 1.0
        
        m = (n * sum_xy - sum_x * sum_y) / denom
        b = (sum_y - m * sum_x) / n
        
        sse = 0.0
        sst = 0.0
        mean_y = sum_y / n
        
        for i in range(n):
            pred = m * i + b
            sse += (y[i] - pred) ** 2
            sst += (y[i] - mean_y) ** 2
            
        r_sq = 1.0 - (sse / sst) if sst != 0 else 0.0
        
        # Standard Error of Estimate (Normalized)
        # S_est = sqrt(SSE / (N-2))
        s_est = math.sqrt(sse / (n - 2)) if n > 2 else 0.0
        norm_std_err = s_est / mean_y if mean_y != 0 else 1.0
        
        norm_slope = m / mean_y if mean_y != 0 else 0.0
        
        return norm_slope, r_sq, norm_std_err

    def _calculate_rsi(self, data):
        """Standard 14-period RSI."""
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

    def _calculate_cov(self, data):
        """Coefficient of Variation (Stdev / Mean)."""
        if len(data) < 2: return 0.0
        try:
            mean = statistics.mean(data)
            if mean == 0: return 0.0
            return statistics.stdev(data) / mean
        except: return 0.0