import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Diversity ===
        self.dna = random.random()
        
        # === Time Window ===
        # Extended window to better capture the true mean trend
        self.window_size = 150 + int(self.dna * 30)
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # We push the floor significantly deeper. 
        # Adaptive Z: Deeper threshold required if R2 is lower.
        self.base_z_threshold = -4.8 - (self.dna * 0.8)
        
        # RSI Confluence: Deep oversold
        self.entry_rsi = 22 + int(self.dna * 4)
        
        # === Structural Filters (Fixing LR_RESIDUAL) ===
        # 1. Variance Ratio: Stricter check for heteroscedasticity.
        # If tail volatility is > 1.45x average, assume regime change/crash.
        self.max_variance_ratio = 1.45
        
        # 2. Residual Momentum: New filter.
        # Checks if residuals are accelerating downwards.
        # We want to buy when the deviation acceleration has paused.
        self.min_residual_slope = -0.002 
        
        # 3. R-Squared Floor
        self.min_r_squared = 0.72
        
        # === Risk Management ===
        self.stop_loss = 0.07        # 7.0% Hard Stop
        self.take_profit = 0.055     # 5.5% Target
        self.max_hold_ticks = 240    # Time limit
        
        self.trade_size = 500.0
        self.min_liq = 800000.0
        self.max_positions = 3
        
        # === State ===
        self.history = {}
        self.positions = {}
        self.cooldowns = {}

    def _calculate_metrics(self, data_deque):
        """
        Calculates OLS, Z-score, Variance Ratio, Residual Momentum, and RSI.
        """
        data = list(data_deque)
        n = len(data)
        if n < self.window_size: return None
        
        # Log-transformation
        try:
            y = [math.log(p) for p in data]
        except ValueError:
            return None
        x = list(range(n))
        
        # OLS Calculation
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * yi for i, yi in enumerate(y))
        sum_xx = sum(i * i for i in x)
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Residuals
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
        
        std_dev = math.sqrt(ss_res / n)
        if std_dev < 1e-10: return None
        
        z_score = residuals[-1] / std_dev
        r_squared = 1.0 - (ss_res / ss_tot)
        
        # --- Variance Ratio (LR_RESIDUAL Fix) ---
        lookback_recent = int(n * 0.15)
        recents = residuals[-lookback_recent:]
        mean_recent = sum(recents) / len(recents)
        var_recent = sum((r - mean_recent)**2 for r in recents) / len(recents)
        var_total = ss_res / n
        vr = var_recent / var_total if var_total > 1e-10 else 999.0
        
        # --- Residual Slope (LR_RESIDUAL Fix) ---
        # Calculate the local trend of the residuals (last 5 points)
        # If this slope is strongly negative, the "knife is still falling" relative to trend
        res_lookback = 5
        res_slice = residuals[-res_lookback:]
        sx = sum(range(res_lookback))
        sy = sum(res_slice)
        sxy = sum(i * r for i, r in enumerate(res_slice))
        sxx = sum(i*i for i in range(res_lookback))
        r_denom = res_lookback * sxx - sx**2
        res_slope = (res_lookback * sxy - sx * sy) / r_denom if r_denom != 0 else 0.0

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
            'slope': slope,
            'r2': r_squared,
            'vr': vr,
            'res_slope': res_slope,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Portfolio Logic (Exit Checks)
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                px = float(prices[sym]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue
                
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
                self.cooldowns[sym] = 40 # Cool down to avoid rebuying same crash
                return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': [exit_reason]}

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        # Shuffle for execution diversity
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                px = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
                if liq < self.min_liq: continue
            except (KeyError, ValueError, TypeError):
                continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(px)
            
            if len(self.history[sym]) < self.window_size: continue
            
            # Compute Metrics
            m = self._calculate_metrics(self.history[sym])
            if not m: continue
            
            # === FILTERS ===
            
            # 1. Structural Integrity (LR_RESIDUAL)
            if m['r2'] < self.min_r_squared: continue
            if m['vr'] > self.max_variance_ratio: continue
            # Ensure the residual itself isn't crashing (Momentum Check)
            if m['res_slope'] < self.min_residual_slope: continue
            
            # 2. Reversion Depth (Z:-3.93 Fix)
            # Use strict threshold
            if m['z'] > self.base_z_threshold: continue
            
            # 3. RSI Confluence
            if m['rsi'] > self.entry_rsi: continue

            # Execute Buy
            amt = self.trade_size / px
            self.positions[sym] = {'entry': px, 'amount': amt, 'ticks': 0}
            
            return {
                'side': 'BUY', 
                'symbol': sym, 
                'amount': amt, 
                'reason': ['DEEP_Z', f'Z:{m["z"]:.2f}']
            }
            
        return None