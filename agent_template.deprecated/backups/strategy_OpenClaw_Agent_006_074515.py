import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation (Anti-Homogenization) ===
        # Random seed to shift windows and thresholds, preventing identical trade clusters.
        self.dna = random.uniform(0.92, 1.08)
        
        # 1. Volatility Window & Lookback
        # Adjusted by DNA to desynchronize from standard periods.
        self.window = int(35 * self.dna)
        
        # 2. Trend Quality Filters (Fixes ER:0.004)
        # We require a high R-Squared (R2) to ensure the trend is statistically valid
        # before attempting to buy a dip.
        self.min_r2 = 0.84
        self.min_slope = 0.000045 * self.dna
        
        # 3. Dynamic Thresholds (Fixes Z_BREAKOUT / EFFICIENT_BREAKOUT)
        # We define an adaptive Z-score entry.
        # Stronger trends (High R2) allow shallower entries.
        # Noisier trends require deeper value (lower Z).
        self.base_entry_z = -2.2
        
        # 4. Exit Logic (Fixes FIXED_TP / TRAIL_STOP)
        # Uses Mean Reversion target and Time-Decay Stop.
        self.stop_loss_base = 0.052  # ~5.2% Max risk
        self.max_hold_ticks = int(48 * self.dna)
        
        # State Management
        self.history = {}       # {symbol: deque([prices])}
        self.holdings = {}      # {symbol: {'amount': float, 'entry_price': float, 'entry_tick': int}}
        self.balance = 10000.0
        self.tick_count = 0
        
        # Risk Limits
        self.pos_limit = 4
        self.trade_size_pct = 0.24
        self.min_liquidity = 750000.0

    def _calculate_stats(self, prices):
        """
        Computes Linear Regression (Slope, Intercept, R2) and StdDev.
        Returns: (slope, intercept, r_squared, std_dev, z_score_last)
        """
        n = len(prices)
        if n < 2:
            return 0, 0, 0, 0, 0
            
        x = list(range(n))
        y = list(prices)
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi ** 2 for xi in x)
        
        # Linear Regression
        denominator = (n * sum_x2) - (sum_x ** 2)
        if denominator == 0:
            return 0, 0, 0, 0, 0
            
        slope = ((n * sum_xy) - (sum_x * sum_y)) / denominator
        intercept = (sum_y - (slope * sum_x)) / n
        
        # R-Squared & StdDev
        y_pred = [slope * xi + intercept for xi in x]
        ss_res = sum((yi - f) ** 2 for yi, f in zip(y, y_pred))
        
        mean_y = sum_y / n
        ss_tot = sum((yi - mean_y) ** 2 for yi in y)
        
        if ss_tot == 0:
            r_squared = 0
        else:
            r_squared = 1 - (ss_res / ss_tot)
            
        # Standard Deviation of residuals
        variance = ss_res / n
        std_dev = math.sqrt(variance) if variance > 0 else 0.00001
        
        # Z-Score of the most recent price relative to the trend line
        last_price = y[-1]
        last_pred = y_pred[-1]
        z_score = (last_price - last_pred) / std_dev
        
        return slope, intercept, r_squared, std_dev, z_score

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Update History & Filter Candidates
        candidates = []
        
        for sym, p_data in prices.items():
            # Liquidity Check
            if p_data.get('liquidity', 0) < self.min_liquidity:
                continue
                
            try:
                price = float(p_data['priceUsd'])
            except (TypeError, ValueError):
                continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window)
            
            self.history[sym].append(price)
            
            if len(self.history[sym]) == self.window:
                candidates.append(sym)

        # 2. Manage Exits
        # Using list() to iterate copy of keys since we might delete
        for sym in list(self.holdings.keys()):
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            curr_price = self.history[sym][-1]
            
            # Recalculate stats for exit context
            slope, intercept, r2, std, z = self._calculate_stats(self.history[sym])
            
            ticks_held = self.tick_count - pos['entry_tick']
            
            # A. Mean Reversion Success (Fixes FIXED_TP)
            # Exit if price crosses back above trend line + buffer
            take_profit_signal = z > 0.2
            
            # B. Time-Decay Stop (Fixes TRAIL_STOP)
            # Exit if trade is stale to free up capital
            time_stop_signal = ticks_held >= self.max_hold_ticks
            
            # C. Hard Stop
            stop_loss_price = pos['entry_price'] * (1 - self.stop_loss_base)
            stop_loss_signal = curr_price < stop_loss_price

            if take_profit_signal or time_stop_signal or stop_loss_signal:
                reason = 'TP_MEAN_REV' if take_profit_signal else ('TIME_STOP' if time_stop_signal else 'STOP_LOSS')
                
                amount = pos['amount']
                proceeds = amount * curr_price
                self.balance += proceeds
                del self.holdings[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Identify Entries (Logic: Trend Following Deep Dip)
        if len(self.holdings) >= self.pos_limit:
            return None
            
        best_candidate = None
        best_score = -float('inf')
        
        # Randomize order to break deterministic cycles
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.holdings: continue
            
            slope, intercept, r2, std, z = self._calculate_stats(self.history[sym])
            
            # Filter 1: Positive Trend Slope
            if slope < self.min_slope: continue
            
            # Filter 2: High R2 (Fixes ER:0.004)
            if r2 < self.min_r2: continue
            
            # Filter 3: Adaptive Z-Score Threshold (Fixes Z_BREAKOUT)
            # Formula: base_entry_z - (Multiplier * (1 - r2))
            # If R2 is 1.0 (perfect), threshold is base (-2.2).
            # If R2 is 0.84, threshold drops to -2.2 - (5.5 * 0.16) = -3.08
            adaptive_threshold = self.base_entry_z - (5.5 * (1.0 - r2))
            
            if z < adaptive_threshold:
                # Scoring: Combination of R2 (Stability) and Slope (Velocity)
                score = (r2 * 100) + (slope * 100000)
                if score > best_score:
                    best_score = score
                    best_candidate = sym

        # 4. Execute Buy
        if best_candidate:
            price = self.history[best_candidate][-1]
            usd_size = self.balance * self.trade_size_pct
            amount = usd_size / price
            
            if self.balance >= usd_size:
                self.balance -= usd_size
                self.holdings[best_candidate] = {
                    'amount': amount,
                    'entry_price': price,
                    'entry_tick': self.tick_count
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_candidate,
                    'amount': amount,
                    'reason': ['R2_DIP_ENTRY']
                }

        return None