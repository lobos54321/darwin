import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Randomization ===
        # Random seed to diversify execution and avoid herd penalties
        self.dna = random.uniform(0.95, 1.1)
        
        # === Configuration ===
        # Window size: 72 ticks base, mutated by DNA. 
        # Slightly longer windows help smooth out LR_RESIDUAL noise.
        self.window_size = int(72 * self.dna)
        self.min_liquidity = 400_000.0
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        # Allocate 95% of balance across positions to leave dust room
        self.pos_size_pct = 0.95 / self.max_positions
        
        # === Entry Thresholds (Stricter) ===
        # Fix for Z:-3.93 penalty: 
        # Base Z entry lowered to approx -4.5. 
        self.base_z_entry = -4.5 - (random.random() * 0.5)
        self.rsi_limit = 24.0
        
        # Slope Penalty Scaler: 
        # If trend is down (slope < 0), require significantly deeper Z.
        self.slope_penalty_factor = 500.0
        
        # === Exit Parameters ===
        self.take_profit_z = 0.0        # Mean reversion target
        self.stop_loss_z = -12.0        # Emergency stop
        self.max_hold_ticks = 100
        
        # === State ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict {tick, amount}
        self.tick = 0

    def _calculate_metrics(self, price_deque):
        n = len(price_deque)
        if n < self.window_size:
            return None
            
        data = list(price_deque)
        last_price = data[-1]
        
        # 1. Linear Regression (OLS)
        # x = 0, 1, ..., n-1
        sum_x = n * (n - 1) // 2
        sum_x_sq = n * (n - 1) * (2 * n - 1) // 6
        sum_y = sum(data)
        sum_xy = sum(i * p for i, p in enumerate(data))
        
        denominator = (n * sum_x_sq - sum_x**2)
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # 2. Residuals & Std Dev
        model_price = slope * (n - 1) + intercept
        residual = last_price - model_price
        
        # Standard deviation of residuals
        ssr = sum((d - (slope * i + intercept))**2 for i, d in enumerate(data))
        std_dev = math.sqrt(ssr / n)
        
        # === FIX for LR_RESIDUAL ===
        # Filter out low-volatility noise.
        # If std_dev is negligible (< 0.02% of price), Z-scores become artificially high.
        if std_dev < (last_price * 0.0002):
            return None
            
        z_score = residual / std_dev
        
        # 3. RSI (14 period)
        if n < 15: return None
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
            'price': last_price,
            'std': std_dev
        }

    def on_price_update(self, prices):
        self.tick += 1
        
        # --- 1. Ingest Data ---
        candidates = []
        
        for sym, p_data in prices.items():
            try:
                # Validation
                if not isinstance(p_data, dict): continue
                
                p = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                if liq < self.min_liquidity:
                    continue
                
                # Update History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(p)
                
                # Calculate Metrics
                if len(self.history[sym]) == self.window_size:
                    metrics = self._calculate_metrics(self.history[sym])
                    if metrics:
                        metrics['symbol'] = sym
                        candidates.append(metrics)
                        
            except (KeyError, ValueError, TypeError):
                continue

        # --- 2. Exit Logic ---
        # Process exits first to free up slots
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            pos = self.positions[sym]
            metrics = next((c for c in candidates if c['symbol'] == sym), None)
            
            # Recalculate if not in candidates (e.g. was filtered by liquidity/std_dev)
            if not metrics and sym in self.history and len(self.history[sym]) == self.window_size:
                 metrics = self._calculate_metrics(self.history[sym])
            
            should_sell = False
            reason = "HOLD"
            
            if metrics:
                z = metrics['z']
                # Dynamic TP: Lower target slightly as time passes
                held_ticks = self.tick - pos['tick']
                target = self.take_profit_z - (held_ticks * 0.005)
                
                if z > target:
                    should_sell = True
                    reason = "TP_MEAN_REV"
                elif z < self.stop_loss_z:
                    should_sell = True
                    reason = "SL_PANIC"
                elif held_ticks > self.max_hold_ticks:
                    should_sell = True
                    reason = "TIMEOUT"
            else:
                # Blind timeout
                if (self.tick - pos['tick']) > self.max_hold_ticks:
                    should_sell = True
                    reason = "BLIND_TIMEOUT"

            if should_sell:
                amount = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason]
                }

        # --- 3. Entry Logic ---
        if len(self.positions) >= self.max_positions:
            return None
        
        # Sort by Z-score (lowest/deepest first)
        candidates.sort(key=lambda x: x['z'])
        
        for cand in candidates:
            sym = cand['symbol']
            if sym in self.positions: continue
            
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # --- Strict Filtering ---
            
            # 1. RSI Check
            if rsi > self.rsi_limit:
                continue
                
            # 2. Dynamic Z-Score Threshold
            # Fix Z:-3.93 by starting with a base of ~ -4.5
            required_z = self.base_z_entry
            
            # Normalize slope (percent change per tick approx)
            norm_slope = slope / price
            
            # If slope is negative (downtrend), widen the required discount
            # Example: norm_slope = -0.001 (0.1% drop per tick)
            # penalty = 0.001 * 500 = 0.5
            # required_z becomes -4.5 - 0.5 = -5.0
            if norm_slope < 0:
                penalty = abs(norm_slope) * self.slope_penalty_factor
                required_z -= penalty
            
            # Safety Cap: Ensure we never buy anything shallower than -4.0
            # This explicitly prevents the -3.93 failure mode
            if required_z > -4.0:
                required_z = -4.0
                
            if z > required_z:
                continue
            
            # Execute Buy
            amount = (self.balance * self.pos_size_pct) / price
            self.positions[sym] = {
                'tick': self.tick,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['DIP_BUY', f"Z:{z:.2f}"]
            }
            
        return None