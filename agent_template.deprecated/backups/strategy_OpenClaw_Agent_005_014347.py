import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Diversity ===
        # Unique seed to prevent homogenized behavior in the Hive Mind
        self.dna = random.random()
        
        # === Time Window ===
        # A 140-160 window stabilizes the OLS against short-term noise while maintaining fit
        self.window_size = 140 + int(self.dna * 20)
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # The penalty at -3.93 implies entries were too early (catching falling knives).
        # We push the Z-score threshold significantly deeper (-4.6 to -5.3).
        self.entry_z_threshold = -4.6 - (self.dna * 0.7)
        
        # RSI Confluence: Strict oversold condition required
        self.entry_rsi = 25 + int(self.dna * 3)
        
        # === Structural Filters (Fixing LR_RESIDUAL) ===
        # 1. Variance Ratio: Checks for heteroscedasticity.
        # If residual variance in the last 15% of the window is > 1.55x the total variance,
        # volatility is expanding rapidly, making mean reversion dangerous.
        self.max_variance_ratio = 1.55
        
        # 2. R-Squared Floor: Ensures the linear trend is valid.
        # Buying a Z-deviation from a line that doesn't fit the data (low R2) is statistical noise.
        self.min_r_squared = 0.65
        
        # 3. Slope Safety: Avoid buying into vertical crashes.
        self.min_slope = -0.005
        
        # === Risk Management ===
        self.stop_loss = 0.08        # 8.0% Hard Stop
        self.take_profit = 0.05      # 5.0% Target
        self.max_hold_ticks = 220    # Time decay exit
        
        self.trade_size = 450.0
        self.min_liq = 600000.0
        self.max_positions = 4
        
        # === State ===
        self.history = {}
        self.positions = {}
        self.cooldowns = {}

    def _calculate_stats(self, data):
        """
        Calculates OLS statistics, Residual Variance Ratio, and RSI.
        """
        n = len(data)
        if n < self.window_size: return None
        
        # Log-transformation for scale invariance
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
        
        # Residuals & Stats
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
            
        # Standard Deviation of Residuals
        std_dev = math.sqrt(ss_res / n) if n > 0 else 0
        if std_dev < 1e-10: return None
        
        z_score = residuals[-1] / std_dev
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
        
        # --- Variance Ratio (LR_RESIDUAL Fix) ---
        # Detects if volatility is exploding at the tail (bad time to enter)
        lookback_recent = int(n * 0.15)
        if lookback_recent < 2: return None
        
        recents = residuals[-lookback_recent:]
        mean_recent = sum(recents) / len(recents)
        var_recent = sum((r - mean_recent)**2 for r in recents) / len(recents)
        var_total = ss_res / n
        
        # Ratio of Recent Variance to Total Variance
        variance_ratio = var_recent / var_total if var_total > 1e-10 else 999.0

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
            'vr': variance_ratio,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Shuffle for execution diversity
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        output = None
        
        for sym in symbols:
            try:
                p_data = prices[sym]
                px = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
            except (KeyError, ValueError, TypeError):
                continue
            
            # === EXIT LOGIC ===
            if sym in self.positions:
                pos = self.positions[sym]
                entry_px = pos['entry']
                amt = pos['amount']
                
                self.positions[sym]['ticks'] += 1
                roi = (px - entry_px) / entry_px
                
                reason = None
                if roi < -self.stop_loss: reason = 'STOP_LOSS'