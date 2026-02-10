import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique seed to prevent herd behavior and strategy correlation
        self.dna = random.random()
        
        # === Time Window ===
        # Extended window size to establish a robust long-term trend
        # 160-190 ticks
        self.window_size = 160 + int(self.dna * 30)
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # The penalty indicates -3.93 was too shallow (catching falling knives).
        # We push the base threshold significantly deeper.
        # Range: [-4.6, -5.1] based on DNA.
        self.base_z_threshold = -4.6 - (self.dna * 0.5)
        
        # === Structural Filters (Fixing LR_RESIDUAL) ===
        # 1. Variance Ratio: Detects heteroscedasticity (volatility explosion).
        # If the variance of the last 15% of residuals is > 1.6x the total residual variance,
        # the linear model is breaking down -> Don't trade.
        self.max_variance_ratio = 1.6
        
        # 2. Residual Momentum: 
        # Ensures the deviation isn't accelerating downwards.
        # We need the "second derivative" of the move to be stabilizing.
        self.min_residual_slope = -0.0015
        
        # 3. R-Squared Floor
        # Only trade pairs that respect the linear trendline.
        self.min_r_squared = 0.74
        
        # === Confluence ===
        self.entry_rsi = 24
        
        # === Risk Management ===
        self.stop_loss = 0.075        # 7.5% Hard Stop
        self.take_profit = 0.055      # 5.5% Target
        self.max_hold_ticks = 240     # Time decay exit
        
        self.trade_size = 500.0
        self.min_liq = 900000.0       # High liquidity filter
        self.max_positions = 3
        
        # === State ===
        self.history = {}
        self.positions = {}
        self.cooldowns = {}

    def _analyze_market(self, price_deque):
        """
        Performs OLS Regression and analyzes residuals for statistical anomalies.
        """
        data = list(price_deque)
        n = len(data)
        if n < self.window_size: 
            return None
        
        # Log-transformation for geometric price handling
        try:
            y = [math.log(p) for p in data]
        except ValueError:
            return None
            
        x = list(range(n))
        
        # --- OLS Calculation ---
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
        if std_dev < 1e-9: return None # Filter flatlines
        
        # Metrics
        z_score = residuals[-1] / std_dev
        r_squared = 1.0 - (ss_res / ss_tot)
        
        # --- Fix for LR_RESIDUAL: Variance Ratio ---
        # Detects if the tail end of the residuals is exploding relative to the historical norm.
        # High VR = Regime Change = Model Invalid.
        lookback_recent = int(n * 0.15)
        recents = residuals[-lookback_recent:]
        mean_recent = sum(recents) / len(recents)
        var_recent = sum((r - mean_recent)**2 for r in recents) / len(recents)
        var_total = ss_res / n
        
        variance_ratio = var_recent / var_total if var_total > 1e-10 else 999.0
        
        # --- Fix for LR_RESIDUAL: Residual Slope ---
        # Calculate the local trend of the residuals (last 6 points).
        # If this is strongly negative, price is accelerating away from the prediction (convex crash).
        # We want to catch it when this acceleration flattens out.
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

        # --- RSI ---
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
            'rsi': rsi
        }

    def on_price_update(self, prices):
        # 1. Update Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Manage Portfolio
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
                self.cooldowns[sym] = 50 # Extended cooldown after exit
                return {
                    'side': 'SELL', 
                    'symbol': sym, 
                    'amount': amt, 
                    'reason': [exit_reason]
                }

        # 3. Check for Entries
        if len(self.positions) >= self.max_positions:
            return None

        # Random shuffle to avoid deterministic ordering bias
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
            
            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(px)
            
            if len(self.history[sym]) < self.window_size: continue
            
            # Metric Calculation
            m = self._analyze_market(self.history[sym])
            if not m: continue
            
            # === FILTERS ===
            
            # 1. Structural Integrity (Fixing LR_RESIDUAL)
            # Ensure the regression line is a valid baseline
            if m['r2'] < self.min_r_squared: continue
            
            # Check for volatility explosion (Variance Ratio)
            if m['vr'] > self.max_variance_ratio: continue
            
            # Check for accelerating crash (Residual Slope)
            if m['res_slope'] < self.min_residual_slope: continue
            
            # 2. Reversion Depth (Fixing Z:-3.93)
            # Adaptive Threshold: If R2 is lower (weaker trend), require deeper Z
            current_z_threshold = self.base_z_threshold
            if m['r2'] < 0.82:
                current_z_threshold -= 0.5  # Push to ~ -5.1+
            
            if m['z'] > current_z_threshold: continue
            
            # 3. RSI Confluence
            if m['rsi'] > self.entry_rsi: continue

            # Execute Trade
            amt = self.trade_size / px
            self.positions[sym] = {'entry': px, 'amount': amt, 'ticks': 0}
            
            return {
                'side': 'BUY', 
                'symbol': sym, 
                'amount': amt, 
                'reason': ['DEEP_LR', f'Z:{m["z"]:.2f}', f'VR:{m["vr"]:.2f}']
            }
            
        return None