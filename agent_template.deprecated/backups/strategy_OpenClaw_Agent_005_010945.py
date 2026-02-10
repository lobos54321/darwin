import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Diversity ===
        # Random seed to prevent herd behavior among instances
        self.dna = random.random()
        
        # === Time Window ===
        # Dynamic window size (100-140) to vary regression horizons
        self.window_size = 100 + int(self.dna * 40)
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # The penalty implies -3.93 was not deep enough.
        # We push the Z-score entry to a deeper "extreme value" zone.
        # Range: -4.2 to -5.0 depending on DNA.
        self.entry_z_threshold = -4.2 - (self.dna * 0.8)
        
        # Strict RSI to confirm momentum exhaustion
        self.rsi_threshold = 12 + int(self.dna * 6) # 12 to 18
        
        # === Structural Filters (Fixing LR_RESIDUAL) ===
        # 1. Slope Acceleration: Avoid buying if the downtrend is accelerating.
        # If the recent slope is X times steeper than the long-term slope, it's a crash, not a dip.
        self.max_slope_acceleration = 1.5 
        
        # 2. Variance Ratio: Heteroskedasticity check.
        # If residual variance is exploding at the tail, the linear model is failing.
        self.max_variance_ratio = 1.8
        
        # === Risk Management ===
        self.stop_loss = 0.08       # 8% Stop Loss (Wide for volatility)
        self.take_profit = 0.035    # 3.5% Take Profit
        self.max_hold_ticks = 240   # Time limit to free up capital
        
        self.trade_size = 300.0
        self.min_liq = 1000000.0
        self.max_positions = 3      # Limited concurrency for safety
        
        # === State ===
        self.history = {}
        self.positions = {}
        self.cooldowns = {}

    def _get_ols_stats(self, data):
        """
        Calculates OLS statistics and Z-score of the last price point.
        """
        n = len(data)
        if n < 10: return None
        
        # Use log prices for better handling of percentage moves
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
        
        # Residuals
        residuals = []
        sum_sq_resid = 0.0
        
        for i, val in enumerate(y):
            pred = slope * i + intercept
            res = val - pred
            residuals.append(res)
            sum_sq_resid += res * res
            
        std_dev = math.sqrt(sum_sq_resid / n) if n > 0 else 0
        if std_dev < 1e-10: return None # No volatility
        
        z_score = residuals[-1] / std_dev
        
        return {
            'slope': slope,
            'z_score': z_score,
            'std_dev': std_dev,
            'residuals': residuals
        }

    def _get_rsi(self, prices, period=14):
        if len(prices) < period + 1: return 50.0
        
        gains = 0.0
        losses = 0.0
        
        for i in range(len(prices) - period, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0: gains += change
            else: losses += abs(change)
            
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

        # 2. Shuffle symbols for execution diversity
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
                
                # Stop Loss
                if roi < -self.stop_loss:
                    del self.positions[sym]
                    self.cooldowns[sym] = 100 # Long cooldown on loss
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['STOP_LOSS']}
                
                # Take Profit
                if roi > self.take_profit:
                    del self.positions[sym]
                    self.cooldowns[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['TAKE_PROFIT']}
                
                # Time Limit
                if ticks > self.max_hold_ticks:
                    del self.positions[sym]
                    self.cooldowns[sym] = 30
                    return {'side': 'SELL', 'symbol': sym, 'amount': amt, 'reason': ['TIME_LIMIT']}
                
                continue # Skip entry logic if in position
            
            # === ENTRY LOGIC ===
            if output is not None: continue
            if len(self.positions) >= self.max_positions: continue
            if sym in self.cooldowns: continue
            
            # Need full window for stats
            if len(self.history[sym]) < self.window_size: continue
            
            full_hist = list(self.history[sym])
            stats = self._get_ols_stats(full_hist)
            if not stats: continue
            
            # 1. Deep Z-Score Filter (Addressing Z:-3.93)
            # Must be strictly below the DNA-modified threshold (e.g., -4.5)
            if stats['z_score'] < self.entry_z_threshold:
                
                # 2. RSI Filter
                rsi = self._get_rsi(full_hist)
                if rsi < self.rsi_threshold:
                    
                    # 3. Structural Filter: Slope Acceleration (Addressing LR_RESIDUAL)
                    # Detect if the crash is accelerating. If recent slope is much steeper than full slope,
                    # the linear model assumptions are breaking down (parabolic move).
                    # We compute stats on the last 25% of the window.
                    subset_len = int(self.window_size * 0.25)
                    recent_hist = full_hist[-subset_len:]
                    recent_stats = self._get_ols_stats(recent_hist)
                    
                    is_accelerating_crash = False
                    if recent_stats:
                        # Only worry if both slopes are negative
                        if stats['slope'] < 0 and recent_stats['slope'] < 0:
                            denom = abs(stats['slope'])
                            if denom < 1e-12: denom = 1e-12
                            
                            ratio = abs(recent_stats['slope']) / denom
                            if ratio > self.max_slope_acceleration:
                                is_accelerating_crash = True
                                
                    if not is_accelerating_crash:
                        
                        # 4. Structural Filter: Variance Ratio (Addressing LR_RESIDUAL)
                        # Check if residuals are expanding (Heteroskedasticity)
                        residuals = stats['residuals']
                        split_idx = int(len(residuals) * 0.8)
                        
                        head_res = residuals[:split_idx]
                        tail_res = residuals[split_idx:]
                        
                        def get_var(arr):
                            if not arr: return 0.0
                            m = sum(arr) / len(arr)
                            return sum((x - m)**2 for x in arr) / len(arr)
                        
                        var_head = get_var(head_res)
                        var_tail = get_var(tail_res)
                        
                        # Avoid div by zero
                        if var_head < 1e-12: var_head = 1e-12
                        
                        var_ratio = var_tail / var_head
                        
                        if var_ratio < self.max_variance_ratio:
                            
                            # === EXECUTE TRADE ===
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
                                'reason': ['DEEP_VAL', f'Z:{stats["z_score"]:.2f}']
                            }
                            return output

        return None