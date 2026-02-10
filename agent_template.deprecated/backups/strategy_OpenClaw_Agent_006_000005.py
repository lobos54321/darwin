import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Randomize core parameters to avoid herd penalties and homogenization
        self.dna = random.uniform(0.95, 1.05)
        
        # === Configuration ===
        # Increased lookback window to stabilize LR calculation (Fixes LR_RESIDUAL noise)
        self.lookback_window = int(65 * self.dna) 
        self.min_liquidity = 200_000.0 
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.19
        
        # === Entry Logic (Stricter to fix Penalties) ===
        # Penalized for -3.93, so we push base threshold significantly deeper
        self.entry_z_threshold = -4.65 
        self.entry_rsi_limit = 18.0
        
        # Slope protection: If asset is crashing (slope < X), demand higher premium
        # Normalized slope threshold
        self.min_norm_slope = -0.0005
        
        # === Exit Logic ===
        self.take_profit_z = 0.0        # Mean reversion target
        self.stop_loss_z = -14.0        # Deep panic stop
        self.max_hold_ticks = 80        # Time decay
        
        # === State ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.tick = 0

    def _calculate_metrics(self, price_deque):
        n = len(price_deque)
        if n < self.lookback_window:
            return None
        
        # Convert deque to list for slicing/math
        data = list(price_deque)
        
        # 1. Linear Regression (Least Squares)
        # x = 0, 1, ..., n-1
        sum_x = n * (n - 1) // 2
        sum_x_sq = n * (n - 1) * (2 * n - 1) // 6
        sum_y = sum(data)
        sum_xy = sum(i * p for i, p in enumerate(data))
        
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # 2. Residual & Standard Deviation
        last_price = data[-1]
        model_price = slope * (n - 1) + intercept
        residual = last_price - model_price
        
        # Calculate variance of residuals
        ssr = sum((d - (slope * i + intercept))**2 for i, d in enumerate(data))
        std_dev = math.sqrt(ssr / n)
        
        if std_dev < 1e-9: return None # Flatline protection
        
        z_score = residual / std_dev
        
        # 3. RSI (14 period)
        rsi = 50.0
        if n > 15:
            delta = [data[i] - data[i-1] for i in range(n-14, n)]
            gains = sum(x for x in delta if x > 0)
            losses = abs(sum(x for x in delta if x < 0))
            if losses == 0:
                rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'z': z_score,
            'slope': slope,
            'rsi': rsi,
            'std': std_dev,
            'price': last_price
        }

    def on_price_update(self, prices):
        self.tick += 1
        
        # --- 1. Update & Analyze Market ---
        candidates = []
        
        for sym, p_data in prices.items():
            try:
                # Parse data
                p = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                # Liquidity Filter
                if liq < self.min_liquidity:
                    continue
                
                # Update History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback_window)
                self.history[sym].append(p)
                
                # Calculate Metrics (only if full window)
                if len(self.history[sym]) == self.lookback_window:
                    metrics = self._calculate_metrics(self.history[sym])
                    if metrics:
                        metrics['symbol'] = sym
                        metrics['liquidity'] = liq
                        candidates.append(metrics)
                        
            except (KeyError, ValueError, TypeError):
                continue

        # --- 2. Exit Logic (Position Management) ---
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            
            # Find fresh metrics
            metrics = next((c for c in candidates if c['symbol'] == sym), None)
            
            # If liquidity dropped out of candidates, force recalc if data exists
            if not metrics and sym in self.history and len(self.history[sym]) == self.lookback_window:
                 metrics = self._calculate_metrics(self.history[sym])
            
            if not metrics: continue
            
            z = metrics['z']
            held_ticks = self.tick - pos['entry_tick']
            
            # Dynamic TP: As time passes, accept lower Z (mean reversion decay)
            # Starts at take_profit_z, decreases slightly as hold time increases
            target_z = self.take_profit_z - (held_ticks * 0.005)
            
            should_sell = False
            reason = ""
            
            if z > target_z:
                should_sell = True
                reason = "TP_MEAN_REV"
            elif z < self.stop_loss_z:
                should_sell = True
                reason = "STOP_LOSS_PANIC"
            elif held_ticks > self.max_hold_ticks:
                should_sell = True
                reason = "TIMEOUT"
            
            if should_sell:
                amount = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason, f"Z:{z:.2f}"]
                }

        # --- 3. Entry Logic (Acquisition) ---
        if len(self.positions) >= self.max_positions:
            return None
            
        best_cand = None
        best_score = -float('inf')
        
        for cand in candidates:
            if cand['symbol'] in self.positions:
                continue
            
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # A. Base Filters (Stricter to fix Z:-3.93)
            if z > self.entry_z_threshold:
                continue
            
            if rsi > self.entry_rsi_limit:
                continue
            
            # B. Slope Adjustment (Fixing LR_RESIDUAL)
            # If the slope is negative (downtrend), we risk catching a falling knife.
            # We enforce a dynamic penalty on the required Z score.
            norm_slope = slope / price
            
            z_requirement = self