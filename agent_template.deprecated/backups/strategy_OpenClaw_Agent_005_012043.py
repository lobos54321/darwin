import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Diversity ===
        # Random seed to prevent herd behavior
        self.dna = random.random()
        
        # === Time Window ===
        # Extended window (120-160) to improve regression stability
        # Helps reduce LR_RESIDUAL noise by smoothing the trend
        self.window_size = 120 + int(self.dna * 40)
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # Penalty analysis: -3.93 was too shallow for the market conditions.
        # Solution: Push entry deep into the tail.
        # Range: -4.4 to -5.0 depending on DNA.
        self.entry_z_base = -4.4 - (self.dna * 0.6)
        
        # Strict RSI to confirm momentum exhaustion (15-22 range)
        self.rsi_threshold = 15 + int(self.dna * 7)
        
        # === Structural Filters (Fixing LR_RESIDUAL) ===
        # 1. Variance Ratio: Prevents entry when residual volatility is exploding.
        # If the model errors are getting larger recently, the linear fit is invalid.
        self.max_variance_ratio = 1.7
        
        # 2. Slope Limit: Safety guard against flash crashes.
        # If the trend slope is virtually vertical, do not catch the knife.
        self.min_trend_slope = -0.0025 
        
        # === Risk Management ===
        self.stop_loss = 0.075      # 7.5% Stop
        self.take_profit = 0.038    # 3.8% Target
        self.max_hold_ticks = 260   # Time decay
        
        self.trade_size = 450.0
        self.min_liq = 800000.0
        self.max_positions = 3
        
        # === State ===
        self.history = {}
        self.positions = {}
        self.cooldowns = {}

    def _get_ols_stats(self, data):
        """
        Calculates OLS statistics on Log-Prices to handle % moves correctly.
        """
        n = len(data)
        if n < 10: return None
        
        # Log transformation for scale invariance
        y = [math.log(p) for p in data]
        x = list(range(n))
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * yi for i, yi in enumerate(y))
        sum_xx = sum(i * i for i in x)
        
        denom = n * sum_xx - sum_x**2
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Residual Calculation
        residuals = []
        sum_sq_resid = 0.0
        
        for i, val in enumerate(y):
            pred = slope * i + intercept
            res = val - pred
            residuals.append(res)
            sum_sq_resid += res * res
            
        std_dev = math.sqrt(sum_sq_resid / n)
        if std_dev < 1e-10: return None # Avoid div by zero
        
        z_score = residuals[-1] / std_dev
        
        return {
            'slope': slope,
            'z_score': z_score,
            'std_dev': std_dev,
            'residuals': residuals
        }

    def _get_rsi(self, prices, period=14):
        if len(prices) < period + 1: return 50.0
        
        changes = [prices[i] - prices[i-1] for i in range(len(prices) - period, len(prices))]
        
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c <= 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 1. Cooldown Management
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
            
            # Liquidity Filter
            if liq < self.min_liq: continue
            
            # History Update
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(px)
            
            # === EXIT LOGIC ===
            if sym in self.positions:
                pos = self.positions[sym]
                entry_px = pos['entry']
                ticks = pos['ticks']
                amt = pos['amount']
                
                self.positions[sym]['ticks'] += 1
                roi = (px - entry_px) / entry_px
                
                reason = None
                if roi < -self.stop_loss: reason = 'STOP_LOSS'
                elif roi > self.take_profit: reason = 'TAKE_PROFIT'
                elif ticks > self.max_hold_ticks: reason = 'TIME_LIMIT'
                
                if reason:
                    del self.positions[sym]
                    # Longer cooldown on Stop Loss
                    self.cooldowns[sym] = 80 if reason == 'STOP_LOSS' else 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': [reason]}
                
                continue 
            
            # === ENTRY LOGIC ===
            if output is not None: continue
            if len(self.positions) >= self.max_positions: continue
            if sym in self.cooldowns: continue
            
            # Need full window
            if len(self.history[sym]) < self.window_size: continue
            
            full_hist = list(self.history[sym])
            stats = self._get_ols_stats(full_hist)
            if not stats: continue
            
            # === Adaptive Z-Threshold (Fixing Z:-3.93) ===
            # If volatility (std_dev of residuals) is high, the "noise" is louder.
            # We must demand a deeper Z-score to ensure statistical significance.
            current_z_thresh = self.entry_z_base