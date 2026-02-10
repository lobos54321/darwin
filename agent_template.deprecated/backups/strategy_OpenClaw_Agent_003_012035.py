import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy DNA ---
        # Unique seed for slight variations to prevent correlation
        self.dna = random.random()
        
        # --- Window Configurations ---
        # Volatility Window: Increased to 50 to provide a more robust baseline for Z-Scores.
        # A larger window prevents a single crash from skewing the mean too quickly.
        self.vol_window = 50
        
        # Regression Window: Short-term structural analysis.
        self.reg_window = 14
        
        # --- PENALTY FIXES ---
        
        # FIX 1: 'Z:-3.93' Penalty (Falling Knife Protection)
        # We tighten the acceptance band. 
        # Previous strategies likely accepted Z < -2.40 which allowed catching "knives".
        # We set a hard floor at -2.25. Anything deeper is ignored as a crash/anomaly.
        self.z_floor = -2.25 
        self.z_ceiling = -1.50
        
        # FIX 2: 'LR_RESIDUAL' Penalty (Structure Quality)
        # We enforce very strict linearity requirements.
        # R-Squared must be > 0.90 (highly linear dip).
        # NRMSE must be < 0.0006 (extremely low noise/error).
        self.min_r_sq = 0.90
        self.max_nrmse = 0.0006
        
        # Liquidity & Volume Filters
        self.min_liquidity = 1_500_000.0  # Raised to filter low-cap manipulation
        self.min_vol_24h = 250_000.0
        
        # Risk Management
        self.max_positions = 5
        self.trade_amount = 1.0
        self.stop_loss = 0.035    # 3.5% (Tightened)
        self.roi_target = 0.021   # 2.1%
        self.timeout = 40         # Reduced timeout to free up capital
        
        # Indicators
        self.rsi_threshold = 28.0 # Stricter oversold condition
        
        # State
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def on_price_update(self, prices):
        """
        Primary strategy loop. 
        Input: prices (dict) -> {'BTC': {'priceUsd': ..., ...}, ...}
        Output: dict {'side':..., 'symbol':..., 'amount':..., 'reason':...} or None
        """
        self.tick_count += 1
        
        # 1. Cooldown Management
        # Remove symbols whose cooldown tick has passed
        expired = [sym for sym, t in self.cooldowns.items() if self.tick_count >= t]
        for sym in expired:
            del self.cooldowns[sym]
            
        # 2. Position Management (Exits)
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
            except (ValueError, KeyError): continue
                
            pos = self.positions[sym]
            roi = (curr_price - pos['entry']) / pos['entry']
            
            reason = None
            if roi <= -self.stop_loss: reason = 'STOP_LOSS'
            elif roi >= self.roi_target: reason = 'TAKE_PROFIT'
            elif self.tick_count - pos['tick'] >= self.timeout: reason = 'TIMEOUT'
            
            if reason:
                del self.positions[sym]
                # Apply cooldown to avoid re-entering the same volatility immediately
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
        random.shuffle(candidates) # Avoid alphabetical bias
        
        for sym in candidates:
            # Skip if active or cooling down
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                vol = float(p_data['volume24h'])
            except (ValueError, KeyError): continue
            
            # Basic Filters
            if liq < self.min_liquidity: continue
            if vol < self.min_vol_24h: continue
            
            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.vol_window + 10)
            self.history[sym].append(price)
            
            # Need full window for robust Z-score
            if len(self.history[sym]) < self.vol_window: continue
            
            series = list(self.history[sym])
            
            # --- SIGNAL PIPELINE ---
            
            # A. Z-Score Band-Pass
            # We calculate Z-score over the full volatility window
            z = self._calculate_z(series)
            
            # FIX: Z:-3.93
            # Strict rejection of falling knives (Z < -2.25)
            # Strict rejection of shallow dips (Z > -1.50)
            if z < self.z_floor or z > self.z_ceiling:
                continue
                
            # B. Linear Regression Structure
            # We check the most recent reg_window ticks for a clean linear dip
            slope, r_sq, nrmse = self._calculate_regression(series[-self.reg_window:])
            
            # FIX: LR_RESIDUAL
            # Reject if the fit is noisy (low R^2 or high Error)
            if r_sq < self.min_r_sq: continue
            if nrmse > self.max_nrmse: continue
            
            # Ensure slope is actually negative (dipping)
            if slope >= -0.0001: continue
            
            # C. RSI Confirmation
            rsi = self._calculate_rsi(series)
            if rsi > self.rsi_threshold: continue
            
            # D. Execution
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

    def _calculate_z(self, data):
        """Calculates Z-Score of the last price against the Volatility Window."""
        window = data[-self.vol_window:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        if stdev == 0: return 0.0
        return (window[-1] - mean) / stdev

    def _calculate_regression(self, data):
        """
        Calculates Slope, R-Squared, and NRMSE for the given data snippet.
        Used to ensure price action is structural, not chaotic.
        """
        n = len(data)
        if n < 3: return 0.0, 0.0, 1.0
        
        x = list(range(n))
        y = data
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x * sum_x
        if denom == 0: return 0.0, 0.0, 1.0
        
        m = (n * sum_xy - sum_x * sum_y) / denom
        b = (sum_y - m * sum_x) / n
        
        # Calculate Error Metrics
        sse = 0.0
        sst = 0.0
        mean_y = sum_y / n
        
        for i in range(n):
            pred = m * i + b
            sse += (y[i] - pred) ** 2
            sst += (y[i] - mean_y) ** 2
            
        rmse = math.sqrt(sse / n)
        nrmse = rmse / mean_y if mean_y != 0 else 1.0
        
        r_sq = 1.0 - (sse / sst) if sst != 0 else 0.0
        
        # Normalize slope
        norm_slope = m / mean_y if mean_y != 0 else 0.0
        
        return norm_slope, r_sq, nrmse

    def _calculate_rsi(self, data, period=14):
        """Standard 14-period RSI."""
        if len(data) < period + 1: return 50.0
        
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        window = changes[-period:]
        
        gains = sum(c for c in window if c > 0)
        losses = sum(abs(c) for c in window if c < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))