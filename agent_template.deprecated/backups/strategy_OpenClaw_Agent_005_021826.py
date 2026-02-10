import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique seed to diversify execution timing and thresholds
        self.dna = random.random()
        
        # === Time Window ===
        # Use a slightly longer window to smooth out noise for the regression
        # 165 - 195 ticks
        self.window_size = 165 + int(self.dna * 30)
        
        # === Entry Thresholds (Addressing Z:-3.93) ===
        # The penalty suggests -3.93 is too shallow. We need to catch deeper deviations.
        # Base threshold pushed to -4.7, adjustable by DNA.
        # Effective range: [-4.7, -5.2]
        self.base_z_threshold = -4.7 - (self.dna * 0.5)
        
        # === Structural Filters (Addressing LR_RESIDUAL) ===
        # 1. Variance Ratio: Detects volatility clustering (heteroscedasticity) at the end of the window.
        # If recent residuals are much more volatile than historical, the model is failing.
        self.max_variance_ratio = 1.55
        
        # 2. Residual Momentum: 
        # Ensures the "knife" is decelerating. We calculate the slope of the residuals.
        # Must not be accelerating downwards.
        self.min_residual_slope = -0.0012
        
        # 3. Trend Quality
        self.min_r_squared = 0.76
        
        # === Confluence ===
        # Stricter RSI to ensure oversold conditions
        self.entry_rsi = 22
        
        # === Risk Management ===
        self.stop_loss = 0.08         # 8% Hard Stop
        self.take_profit = 0.055      # 5.5% Target
        self.max_hold_ticks = 250     # Time decay exit
        
        self.trade_size = 500.0
        self.min_liq = 1_000_000.0    # Increased liquidity filter
        self.max_positions = 3
        
        # === State ===
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.cycle_count = 0

    def _calculate_ols(self, data):
        """
        Performs OLS Regression on log-prices and analyzes residuals.
        """
        n = len(data)
        if n < self.window_size: 
            return None
        
        # Log-transform for geometric handling
        try:
            y = [math.log(p) for p in data]
        except ValueError:
            return None
            
        x = list(range(n))
        
        # --- OLS Statistics ---
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i * i for i in x)
        sum_xy = sum(i * y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # --- Residual Analysis ---
        residuals = []
        ss_res = 0.0
        ss_tot = 0.0
        mean_y = sum_y / n
        
        for i, val in enumerate(y):
            pred = slope * i + intercept
            res = val - pred
            residuals.append(res)
            ss_res += res * res
            ss_tot += (val - mean_y) ** 2
            
        if ss_tot == 0: return None
        
        # Standard Deviation of Residuals
        std_dev = math.sqrt(ss_res / n)
        if std_dev < 1e-9: return None 
        
        # Core Metrics
        z_score = residuals[-1] / std_dev
        r_squared = 1.0 - (ss_res / ss_tot)
        
        # --- Filter: Variance Ratio (LR_RESIDUAL Fix) ---
        # Compare variance of the last 15% of residuals to the total variance.
        # High ratio = volatility explosion = unpredictable.
        lookback_recent = int(n * 0.15)
        recents = residuals[-lookback_recent:]
        mean_recent = sum(recents) / len(recents)
        var_recent = sum((r - mean_recent)**2 for r in recents) / len(recents)
        var_total = ss_res / n
        
        variance_ratio = var_recent / var_total if var_total > 1e-10 else 999.0
        
        # --- Filter: Residual Slope (LR_RESIDUAL Fix) ---
        # Calculate local trend of the last 6 residuals.
        # We want to avoid catching knives that are accelerating away from the model.
        res_lookback = 6
        res_slice = residuals[-res_lookback:]
        rs_x = list(range(res_lookback))
        rs_sx = sum(rs_x)
        rs_sy = sum(res_slice)
        rs_sxy = sum(i * r for i, r in enumerate(res_slice))
        rs_sxx = sum(i*i for i in rs_x)
        rs_denom = res_lookback * rs_sxx - rs_sx**2
        
        res_slope = 0.0
        if rs_denom != 0:
            res_slope = (res_lookback * rs_sxy - rs_sx * rs_sy) / rs_denom

        # --- Indicator: RSI ---
        period = 14
        deltas = [data[i] - data[i-1] for i in range(n - period, n)]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d <= 0)
        
        if losses == 0: rsi = 100.0
        elif gains == 0: rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))

        return {
            'z': z_score,
            'r2': r_squared,
            'vr': variance_ratio,
            'res_slope': res_slope,
            'rsi': rsi,
            'trend_slope': slope
        }

    def on_price_update(self, prices):
        # 1. Update Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Portfolio Management
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                px = float(prices[sym]['priceUsd'])
            except: continue
                
            pos = self.positions[sym]
            pos['ticks'] += 1
            roi = (px - pos['entry']) / pos['entry']
            
            exit_reason = None
            if roi <= -self.stop_loss: exit_reason = 'STOP_LOSS'
            elif roi >= self.take_profit: exit_reason = 'TAKE_PROFIT'
            elif pos['ticks'] >= self.max_hold_ticks: exit_reason = 'TIME_DECAY'
            
            if exit_reason:
                amt = pos['amount']
                del self.positions[sym]
                self.cooldowns[sym] = 60 # Cooldown after trade
                return {
                    'side': 'SELL', 
                    'symbol': sym, 
                    'amount': amt, 
                    'reason': [exit_reason]
                }

        # 3. New Entry Scan
        if len(self.positions) >= self.max_positions:
            return None

        # Shuffle candidates to prevent deterministic ordering bias
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                px = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
                if liq < self.min_liq: continue
            except: continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(px)
            
            if len(self.history[sym]) < self.window_size: continue
            
            # Analyze
            m = self._calculate_ols(self.history[sym])
            if not m: continue
            
            # === FILTERS ===
            
            # 1. Trend Line Integrity (LR Filter)
            if m['r2'] < self.min_r_squared: continue
            
            # 2. Residual Structure (LR_RESIDUAL Fix)
            # Check for volatility explosion
            if m['vr'] > self.max_variance_ratio: continue
            # Check for accelerating crash
            if m['res_slope'] < self.min_residual_slope: continue
            
            # 3. Adaptive Z-Score Threshold (Z:-3.93 Fix)
            # If the overall trend is negative (Bearish), we need an even deeper dip to buy.
            # If trend is positive, we can stick to the base deep threshold.
            adjusted_z_threshold = self.base_z_threshold
            if m['trend_slope'] < 0:
                adjusted_z_threshold -= 0.3 # Push deeper for bearish trends
                
            if m['z'] > adjusted_z_threshold: continue
            
            # 4. RSI Confluence
            if m['rsi'] > self.entry_rsi: continue

            # Execute Trade
            amt = self.trade_size / px
            self.positions[sym] = {'entry': px, 'amount': amt, 'ticks': 0}
            
            return {
                'side': 'BUY', 
                'symbol': sym, 
                'amount': amt, 
                'reason': ['DEEP_OLS', f'Z:{m["z"]:.2f}', f'VR:{m["vr"]:.2f}']
            }
            
        return None