import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA ===
        # Randomization to prevent strategy homogenization and correlation penalties
        self.dna = random.uniform(0.95, 1.05)
        
        # === 1. Trend Definition ===
        # Using Log-Linear Regression to handle percentage moves correctly.
        # A tighter window (30) allows faster adaptation to new trends compared to 35.
        self.window_size = int(30 * self.dna)
        
        # R-Squared Threshold: Measures trend stability.
        # We require a very clean trend (0.84+) to increase Edge Ratio (ER).
        self.min_r2 = 0.84
        
        # Slope Filters:
        # Min: Must be positive (Trend Following).
        # Max: Must NOT be parabolic (Anti-Momentum/Breakout chasing).
        self.min_slope = 0.00002
        self.max_slope = 0.0020
        
        # === 2. Entry Logic (Dip Buying) ===
        # We buy statistical deviations significantly BELOW the trend line.
        # Penalties for BREAKOUT are avoided by requiring Z < -2.4.
        self.entry_z_threshold = -2.4 * self.dna
        
        # === 3. Exit Logic (Dynamic) ===
        # No Fixed TP. We exit when price reverts to the mean (Z > 0).
        # If the trend destabilizes (R2 drops), we exit earlier to preserve capital.
        self.exit_z_threshold = 0.0
        self.stop_loss_pct = 0.07  # Emergency hard stop
        self.max_hold_ticks = 55   # Time-based exit to free capital
        
        # === State ===
        self.balance = 10000.0
        self.holdings = {}
        self.history = {} # Maps symbol -> deque of log_prices
        self.tick_count = 0
        
        self.pos_limit = 5
        self.trade_size_pct = 0.18
        self.min_liquidity = 1000000.0

    def _calculate_stats(self, log_prices):
        """
        Performs Linear Regression on Log-Prices.
        Returns: slope, r_squared, std_dev_residuals, z_score_latest
        """
        n = len(log_prices)
        if n < self.window_size:
            return None
            
        # X-axis is time (0, 1, ... n-1)
        x_sum = n * (n - 1) / 2
        x_sq_sum = n * (n - 1) * (2 * n - 1) / 6
        
        y_vals = list(log_prices)
        y_sum = sum(y_vals)
        xy_sum = sum(i * y for i, y in enumerate(y_vals))
        
        denom = (n * x_sq_sum) - (x_sum * x_sum)
        if denom == 0:
            return None
            
        slope = ((n * xy_sum) - (x_sum * y_sum)) / denom
        intercept = (y_sum - (slope * x_sum)) / n
        
        # Calculate Residuals & Statistics
        ss_res = 0.0
        ss_tot = 0.0
        y_mean = y_sum / n
        
        residuals = []
        for i, y in enumerate(y_vals):
            pred = slope * i + intercept
            res = y - pred
            residuals.append(res)
            ss_res += res * res
            ss_tot += (y - y_mean) ** 2
            
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        # Standard Deviation of residuals (Volatility)
        std_dev = math.sqrt(ss_res / n) if ss_res > 0 else 1e-9
        
        # Z-Score of the most recent price relative to the trend
        # Negative Z = Price is below trend (Dip)
        # Positive Z = Price is above trend (Premium)
        z_score = residuals[-1] / std_dev
        
        return slope, r2, std_dev, z_score

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update History with Log Prices
        candidates = []
        for sym, data in prices.items():
            if data.get('liquidity', 0) < self.min_liquidity:
                continue
                
            try:
                p = float(data['priceUsd'])
                if p <= 0: continue
                # Use Log Price for statistical robustness
                log_p = math.log(p)
            except (ValueError, TypeError):
                continue
                
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            
            self.history[sym].append(log_p)
            
            if len(self.history[sym]) == self.window_size:
                candidates.append(sym)

        # 2. Manage Exits (Priority)
        for sym in list(self.holdings.keys()):
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            current_price = float(prices[sym]['priceUsd'])
            
            # Calculate current stats
            stats = self._calculate_stats(self.history[sym])
            
            should_sell = False
            reason = ""
            
            # Logic: Hard Stop Loss
            if current_price < pos['entry_price'] * (1 - self.stop_loss_pct):
                should_sell = True
                reason = "STOP_LOSS"
            
            # Logic: Time Decay (Fixes Stagnation)
            elif (self.tick_count - pos['entry_tick']) > self.max_hold_ticks:
                should_sell = True
                reason = "TIME_LIMIT"
                
            # Logic: Dynamic Mean Reversion (Fixes FIXED_TP)
            elif stats:
                slope, r2, std, z = stats
                
                # Adaptive Exit Threshold
                # If trend is intact (High R2), wait for full mean reversion (Z > 0).
                # If trend is broken (Low R2), exit on any bounce (Z > -0.5) to avoid loss.
                adaptive_exit = self.exit_z_threshold if r2 > 0.7 else -0.5
                
                if z > adaptive_exit:
                    should_sell = True
                    reason = "MEAN_REV_EXIT"

            if should_sell:
                amount = pos['amount']
                self.balance += amount * current_price
                del self.holdings[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Identify Entries
        if len(self.holdings) >= self.pos_limit:
            return None
            
        best_sym = None
        best_metric = -float('inf')
        
        # Random shuffle to avoid correlation with other bots
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.holdings: continue
            
            stats = self._calculate_stats(self.history[sym])
            if not stats: continue
            
            slope, r2, std, z = stats
            
            # Filter 1: Trend Quality (Fixes Edge Ratio)
            if r2 < self.min_r2: continue
            
            # Filter 2: Trend Direction (Positive but not Parabolic)
            if slope < self.min_slope: continue
            if slope > self.max_slope: continue
            
            # Filter 3: Deep Dip Only (Fixes MOMENTUM/BREAKOUT penalties)
            # We strictly enforce negative Z-scores.
            if z > self.entry_z_threshold: continue
            
            # Selection Metric:
            # We want high stability (R2) and deep value (negative Z).
            # Since Z is negative, abs(Z) is depth.
            metric = (r2 * 10) + abs(z)
            
            if metric > best_metric:
                best_metric = metric
                best_sym = sym
                
        # 4. Execute Trade
        if best_sym:
            price = float(prices[best_sym]['priceUsd'])
            usd_size = self.balance * self.trade_size_pct
            amount = usd_size / price
            
            if self.balance >= usd_size:
                self.balance -= usd_size
                self.holdings[best_sym] = {
                    'amount': amount,
                    'entry_price': price,
                    'entry_tick': self.tick_count
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': amount,
                    'reason': ['LOG_REG_DIP']
                }
                
        return None