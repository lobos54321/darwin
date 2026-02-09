import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to diversify execution and window parameters slightly
        self.dna = random.random()
        
        # === Time Window ===
        # Extended window (200+) to improve OLS stability and reduce 'LR_RESIDUAL' noise.
        self.window_size = 200 + int(self.dna * 40)
        
        # === Liquidity Filter ===
        # Increased to prevent slippage on thin books
        self.min_liquidity = 1_500_000.0
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # The penalty indicates -3.93 was too shallow.
        # We set a base of -4.85 and adjust dynamically based on trend.
        self.base_z_threshold = -4.85 - (self.dna * 0.3)
        
        # === Structural Filters (Fixing LR_RESIDUAL) ===
        # 1. Variance Ratio: Limits volatility clustering (heteroscedasticity).
        # Strict limit: recent variance cannot exceed 1.45x average variance.
        self.max_variance_ratio = 1.45
        
        # 2. Residual Slope: Prevents catching 'accelerating' knives.
        # Residuals must be flattening (slope ~= 0) or turning up.
        self.min_residual_slope = -0.0003
        
        # 3. Model Fit
        self.min_r_squared = 0.78
        
        # === Confluence ===
        self.entry_rsi = 21
        
        # === Risk Management ===
        self.stop_loss = 0.09        # 9% Hard Stop (Wider for deep catching)
        self.take_profit = 0.06      # 6% Target
        self.max_hold_ticks = 320    # Time based exit
        
        self.trade_size = 600.0
        self.max_positions = 4
        
        # === State ===
        self.history = {}
        self.positions = {}
        self.cooldowns = {}

    def _calculate_ols(self, data):
        """
        Calculates OLS statistics, residuals, and structural health metrics.
        """
        n = len(data)
        if n < self.window_size: 
            return None
        
        # Log-transform for geometric progression
        try:
            y = [math.log(p) for p in data]
        except ValueError:
            return None
            
        x = list(range(n))
        
        # --- OLS Regression ---
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
            
        if ss_tot == 0 or ss_res == 0: return None
        
        # Derived Metrics
        r_squared = 1.0 - (ss_res / ss_tot)
        std_dev = math.sqrt(ss_res / n)
        
        if std_dev < 1e-10: return None
        
        z_score = residuals[-1] / std_dev
        
        # --- Filter 1: Variance Ratio (LR_RESIDUAL Fix) ---
        # Detect if the model is breaking down due to volatility explosion.
        # Check last 10% of data vs global variance.
        lookback_recent = max(5, int(n * 0.1))
        recents = residuals[-lookback_recent:]
        mean_recent = sum(recents) / len(recents)
        var_recent = sum((r - mean_recent)**2 for r in recents) / len(recents)
        var_total = ss_res / n
        
        variance_ratio = var_recent / var_total if var_total > 0 else 999.0
        
        # --- Filter 2: Residual Slope (LR_RESIDUAL Fix) ---
        # Analyze local trend of the last 8 residuals.
        # If residuals are steeply negative, price is accelerating away from mean (falling knife).
        res_lookback = 8
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
        rsi = 50.0
        period = 14
        if n > period + 1:
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
            'trend_slope': slope,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        # 1. Update Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Portfolio Management (Exits)
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
                self.cooldowns[sym] = 80 # Extended cooldown
                return {
                    'side': 'SELL', 
                    'symbol': sym, 
                    'amount': amt, 
                    'reason': [exit_reason]
                }

        # 3. Entry Scan
        if len(self.positions) >= self.max_positions:
            return None

        # Randomize scan order
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                px = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
                if liq < self.min_liquidity: continue
            except: continue
            
            # History Management
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(px)
            
            if len(self.history[sym]) < self.window_size: continue
            
            # Analytics
            m = self._calculate_ols(self.history[sym])
            if not m: continue
            
            # === CRITICAL FILTERS ===
            
            # 1. Structural Integrity (Addressing LR_RESIDUAL)
            if m['r2'] < self.min_r_squared: continue
            if m['vr'] > self.max_variance_ratio: continue
            
            # Check Residual Slope: 
            # If negative, the dip is accelerating (Knife). Wait for flattening (slope >= -0.0003).
            if m['res_slope'] < self.min_residual_slope: continue
            
            # 2. Z-Score Depth (Addressing Z:-3.93)
            # Dynamic adjustment: If main trend is Down, require deeper Z to account for momentum.
            current_z_threshold = self.base_z_threshold
            if m['trend_slope'] < 0:
                # Bear market penalty: Push threshold from -4.85 to ~ -5.35
                current_z_threshold -= 0.5
                
            if m['z'] > current_z_threshold: continue
            
            # 3. Confluence
            if m['rsi'] > self.entry_rsi: continue

            # Execute Trade
            amt = self.trade_size / px
            self.positions[sym] = {'entry': px, 'amount': amt, 'ticks': 0}
            
            return {
                'side': 'BUY', 
                'symbol': sym, 
                'amount': amt, 
                'reason': ['DEEP_OLS', f'Z:{m["z"]:.2f}']
            }
            
        return None