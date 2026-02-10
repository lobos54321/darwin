import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Uniqueness & Parametrization ===
        # Random seed to diversify execution and avoid herd behavior
        self.dna = random.random()
        
        # === Data Window ===
        # Extended window (120-140 ticks) for robust OLS trend estimation.
        # A longer window smoothes out noise and provides a stronger baseline 
        # for statistical deviation checks.
        self.window_size = 120 + int(self.dna * 20)
        
        # === Liquidity Filter ===
        # High liquidity requirement (3.5M) to ensure we trade established assets
        # and avoid slippage or manipulation in thin markets.
        self.min_liquidity = 3_500_000.0
        
        # === Entry Logic (Stricter) ===
        # 1. Z-Score (Statistical Deviation):
        #    We require price to be > 4.2 standard deviations below the trend line.
        #    This is significantly stricter than typical -2.0 or -3.0 thresholds,
        #    specifically to address the 'DIP_BUY' and 'OVERSOLD' penalties by 
        #    only catching extreme anomalies (black swan wicks).
        self.entry_z_score = -4.2
        
        # 2. Efficiency Ratio (ER) Filter:
        #    ER measures the 'efficiency' of the price path (Fractal Dimension).
        #    Low ER (< 0.35) implies Choppy/Mean-Reverting behavior.
        #    High ER (> 0.35) implies a Strong Trend (Crash).
        #    We REJECT entries if ER is high to avoid catching falling knives.
        self.max_efficiency_ratio = 0.35
        
        # 3. Slope Filter:
        #    If the regression slope is too negative, the asset is in a downtrend.
        #    We reject these setups to avoid buying into a "slow bleed".
        self.min_slope = -0.00015
        
        # === Risk Management ===
        self.stop_loss = 0.07       # 7% Hard Stop
        self.take_profit = 0.04     # 4% Target Take Profit
        self.max_hold_ticks = 250   # Max holding time to free up capital
        
        self.trade_size = 1500.0
        self.max_positions = 5
        
        # === State Management ===
        self.history = {}       # {symbol: deque([log_prices])}
        self.positions = {}     # {symbol: {entry, amount, ticks}}
        self.cooldowns = {}     # {symbol: int}

    def _get_ols_stats(self, data):
        """
        Calculates OLS Z-Score, Slope, and Efficiency Ratio.
        Returns Z-Score if filters pass, else None.
        """
        n = len(data)
        if n < self.window_size:
            return None
            
        y = list(data)
        x = list(range(n))
        
        # --- 1. Efficiency Ratio (ER) Check ---
        # ER = Net Move / Sum of Absolute Moves
        net_change = abs(y[-1] - y[0])
        sum_abs_change = sum(abs(y[i] - y[i-1]) for i in range(1, n))
        
        er = 1.0
        if sum_abs_change > 0:
            er = net_change / sum_abs_change
            
        # Filter: If market is trending strongly (High ER), ignore (it's likely a crash)
        if er > self.max_efficiency_ratio:
            return None
            
        # --- 2. Linear Regression (OLS) ---
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*y[i] for i in range(n))
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Filter: If trend is steeply down, do not buy
        if slope < self.min_slope:
            return None
            
        # --- 3. Z-Score (Residual Analysis) ---
        # Calculate deviation of current price from the regression line
        last_pred = slope * (n - 1) + intercept
        last_resid = y[-1] - last_pred
        
        # Calculate standard deviation of residuals
        ss_res = 0.0
        for i in range(n):
            pred = slope * i + intercept
            res = y[i] - pred
            ss_res += res * res
            
        std_dev = math.sqrt(ss_res / n)
        
        if std_dev < 1e-10: return None
        
        z_score = last_resid / std_dev
        
        return z_score

    def on_price_update(self, prices):
        # 1. Cooldown Management
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Portfolio Management (Check Exits)
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            try:
                current_price = float(prices[sym]['priceUsd'])
            except: continue
                
            pos = self.positions[sym]
            pos['ticks']