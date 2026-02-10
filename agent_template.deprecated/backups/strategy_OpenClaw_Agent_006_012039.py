import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to vary parameters and avoid herd homogenization
        self.dna = random.uniform(0.9, 1.15)
        self.risk_factor = random.uniform(0.9, 1.05)
        
        # === Configuration ===
        # Increased lookback window to 75-90 ticks to fix LR_RESIDUAL noise
        self.lookback_window = int(80 * self.dna)
        self.min_liquidity = 250_000.0
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.98 / self.max_positions
        
        # === Entry Thresholds (Significantly Stricter) ===
        # Previous penalty at -3.93 implies we need a much deeper floor.
        # We set a base randomized floor around -4.8 to -5.2
        self.base_z_threshold = -4.85 - (random.random() * 0.4)
        self.rsi_limit = 20.0 * self.risk_factor
        
        # Slope Penalty: Penalize falling knives
        # If trend is down, require Z to be even deeper
        self.slope_penalty_scaler = 300.0
        
        # === Exit Parameters ===
        self.take_profit_z = 0.2        # Wait for mean crossing
        self.stop_loss_z = -14.5        # Deep panic stop
        self.max_hold_ticks = 100       # Patience
        
        # === State ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict {tick, amount, entry_z}
        self.tick = 0

    def _calculate_metrics(self, price_deque):
        n = len(price_deque)
        if n < self.lookback_window:
            return None
        
        data = list(price_deque)
        
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
        last_price = data[-1]
        model_price = slope * (n - 1) + intercept
        residual = last_price - model_price
        
        # Calculate standard deviation of residuals
        ssr = sum((d - (slope * i + intercept))**2 for i, d in enumerate(data))
        std_dev = math.sqrt(ssr / n)
        
        if std_dev < 1e-9: return None
        
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
        
        # --- 1. Update Data & Generate Candidates ---
        candidates = []
        
        for sym, p_data in prices.items():
            try:
                if not isinstance(p_data, dict): continue
                
                p = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                if liq < self.min_liquidity:
                    continue
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback_window)
                self.history[sym].append(p)
                
                if len(self.history[sym]) == self.lookback_window:
                    metrics = self._calculate_metrics(self.history[sym])
                    if metrics:
                        metrics['symbol'] = sym
                        candidates.append(metrics)
                        
            except (KeyError, ValueError, TypeError):
                continue

        # --- 2. Exit Logic ---
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            pos = self.positions[sym]
            metrics = next((c for c in candidates if c['symbol'] == sym), None)
            
            # Fallback calculation if not in candidates (e.g. liq drop)
            if not metrics and sym in self.history and len(self.history[sym]) == self.lookback_window:
                 metrics = self._calculate_metrics(self.history[sym])
            
            should_sell = False
            reason = "HOLD"
            
            if metrics:
                z = metrics['z']
                held_ticks = self.tick - pos['tick']
                
                # Dynamic Take Profit: decays over time to force exit
                target_z = self.take_profit_z - (held_ticks * 0.008)
                
                if z > target_z:
                    should_sell = True
                    reason = "TP_MEAN_REV"
                elif z < self.stop_loss_z:
                    should_sell = True
                    reason = "SL_PANIC"
                elif held_ticks > self.max_hold_ticks:
                    should_sell = True
                    reason = "TIMEOUT"
            else:
                # Blind timeout if no data
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
        
        # Sort candidates by lowest Z first (deepest dips)
        candidates.sort(key=lambda x: x['z'])
        
        for cand in candidates:
            sym = cand['symbol']
            if sym in self.positions: continue
            
            z = cand['z']
            rsi = cand['rsi']
            slope = cand['slope']
            price = cand['price']
            
            # A. Base Filters
            # Fix Z:-3.93 by enforcing strict base floor
            if z > self.base_z_threshold:
                continue
            
            if rsi > self.rsi_limit:
                continue
                
            # B. Slope-Adjusted Threshold (Fix LR_RESIDUAL)
            # If the slope is negative (downtrend), buying the dip is riskier.
            # We enforce a dynamic penalty on the Z-score requirement.
            # Normalized slope = slope / price
            norm_slope = slope / price
            
            required_z = self.base_z_threshold
            
            if norm_slope < 0:
                # Calculate penalty: steep drop -> lower threshold
                # Example: norm_slope -0.001 * 300 = -0.3
                # New threshold: -4.8 - 0.3 = -5.1
                penalty = norm_slope * self.slope_penalty_scaler
                required_z += penalty
            
            if z > required_z:
                continue
            
            # Entry execution
            amount = (self.balance * self.pos_size_pct) / price
            self.positions[sym] = {
                'tick': self.tick,
                'amount': amount,
                'entry_z': z
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['DIP_BUY', f"Z:{z:.2f}"]
            }
            
        return None