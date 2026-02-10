import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Diversity ===
        # Unique seed for parameter diversification
        self.dna = random.random()
        
        # === Time Window ===
        # Window size (130-170) provides enough data for robust OLS while remaining reactive
        self.window_size = 130 + int(self.dna * 40)
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # The penalty at Z:-3.93 indicates the previous floor was too shallow for the volatility.
        # We push the threshold deeper into the tail (-4.8 to -5.5).
        self.entry_z_threshold = -4.8 - (self.dna * 0.7)
        
        # RSI Confluence: Strict oversold condition required
        self.entry_rsi = 21 + int(self.dna * 2)
        
        # === Structural Filters (Fixing LR_RESIDUAL) ===
        # 1. Variance Ratio: Checks for heteroscedasticity.
        # If the variance of residuals in the last 20% of the window is significantly
        # higher than the total variance, the linear model is failing (regime change).
        self.max_variance_ratio = 1.6
        
        # 2. R-Squared Floor: Ensures the linear fit is actually valid.
        # Buying a Z-deviation from a line that doesn't fit the data (low R2) is gambling.
        self.min_r_squared = 0.60
        
        # 3. Slope Safety: Avoid catching falling knives with near-vertical drops.
        self.min_slope = -0.003
        
        # === Risk Management ===
        self.stop_loss = 0.07        # 7.0% Hard Stop
        self.take_profit = 0.042     # 4.2% Target
        self.max_hold_ticks = 240    # Time decay exit
        
        self.trade_size = 450.0
        self.min_liq = 850000.0
        self.max_positions = 3
        
        # === State ===
        self.history = {}
        self.positions = {}
        self.cooldowns = {}

    def _calculate_stats(self, data):
        """
        Calculates OLS statistics and RSI.
        Returns None if data is insufficient or invalid.
        """
        n = len(data)
        if n < self.window_size: return None
        
        # Log-transformation for scale invariance
        y = [math.log(p) for p in data]
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
        lookback_recent = int(n * 0.2)
        recents = residuals[-lookback_recent:]
        if len(recents) < 2: return None
        
        mean_recent = sum(recents) / len(recents)
        var_recent = sum((r - mean_recent)**2 for r in recents) / len(recents)
        var_total = ss_res / n
        
        variance_ratio = var_recent / var_total if var_total > 0 else 999.0

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
                elif roi > self.take_profit: reason = 'TAKE_PROFIT'
                elif self.positions[sym]['ticks'] > self.max_hold_ticks: reason = 'TIME_LIMIT'
                
                if reason:
                    del self.positions[sym]
                    # Extended cooldown after a loss to avoid revenge trading
                    self.cooldowns[sym] = 80 if reason == 'STOP_LOSS' else 30
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': [reason]}
                
                continue 
            
            # === ENTRY LOGIC ===
            if output is not None: continue
            if len(self.positions) >= self.max_positions: continue
            if sym in self.cooldowns: continue
            
            # Liquidity Filter
            if liq < self.min_liq: continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(px)
            
            if len(self.history[sym]) < self.window_size: continue
            
            # Calculate Stats
            stats = self._calculate_stats(list(self.history[sym]))
            if not stats: continue
            
            # === Applying Penalty Fixes ===
            
            # 1. Slope Guard
            if stats['slope'] < self.min_slope: continue
            
            # 2. LR_RESIDUAL Fix: Variance Ratio Check
            # Rejects entries where residual noise is expanding rapidly
            if stats['vr'] > self.max_variance_ratio: continue
            
            # 3. LR_RESIDUAL Fix: R-Squared Check
            # Rejects entries where the linear regression is a poor fit
            if stats['r2'] < self.min_r_squared: continue
            
            # 4. Z:-3.93 Fix: Deep Threshold
            # Must be significantly deeper than the penalized level
            if stats['z'] > self.entry_z_threshold: continue
            
            # 5. RSI Confluence
            if stats['rsi'] > self.entry_rsi: continue
            
            # Valid Entry
            amount = self.trade_size / px
            self.positions[sym] = {
                'entry': px,
                'amount': amount,
                'ticks': 0
            }
            
            output = {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['DEEP_Z_FIT', f"Z:{stats['z']:.2f}", f"VR:{stats['vr']:.2f}"]
            }
            
        return output