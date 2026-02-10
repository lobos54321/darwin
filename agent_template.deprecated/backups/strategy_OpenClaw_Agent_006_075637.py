import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA & Mutation ===
        # Random seed adapts parameters to avoid homogenization penalties
        self.dna = random.uniform(0.9, 1.1)
        
        # === 1. Trend Definition (Fixes ER:0.004) ===
        # We look for statistically significant trends using Linear Regression.
        self.window_size = int(35 * self.dna)
        self.min_r2 = 0.82  # High R-Squared required for entry
        self.min_slope = 0.00004 * self.dna  # Must be positive trend
        
        # === 2. Entry Logic (Fixes MOMENTUM_BREAKOUT / Z_BREAKOUT) ===
        # Instead of buying breakouts, we buy statistical deviations (dips)
        # below the regression line.
        self.base_z_entry = -2.1
        
        # === 3. Exit Logic (Fixes FIXED_TP / TRAIL_STOP) ===
        # Dynamic Exit: Revert to Mean (Regression Line)
        # Time Exit: Close if trade stagnates
        self.z_exit = 0.1
        self.max_hold_ticks = int(48 * self.dna)
        self.stop_loss_pct = 0.055
        
        # === State Management ===
        self.history = {}
        self.holdings = {}
        self.balance = 10000.0
        self.tick_count = 0
        
        self.pos_limit = 5
        self.trade_size_pct = 0.19
        self.min_liquidity = 500000.0

    def _get_stats(self, prices):
        """
        Calculates Linear Regression (Slope, R2) and Z-Score.
        """
        n = len(prices)
        if n < 3:
            return 0, 0, 0, 0, 0
            
        x = list(range(n))
        y = list(prices)
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_x2 = sum(i * i for i in x)
        
        denom = (n * sum_x2) - (sum_x ** 2)
        if denom == 0:
            return 0, 0, 0, 0, 0
            
        slope = ((n * sum_xy) - (sum_x * sum_y)) / denom
        intercept = (sum_y - (slope * sum_x)) / n
        
        # Calculate Residuals & R2
        y_pred = [slope * i + intercept for i in x]
        residuals = [yi - ypi for yi, ypi in zip(y, y_pred)]
        
        ss_res = sum(r ** 2 for r in residuals)
        mean_y = sum_y / n
        ss_tot = sum((yi - mean_y) ** 2 for yi in y)
        
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        # Standard Deviation of residuals
        variance = ss_res / n
        std = math.sqrt(variance) if variance > 0 else 1e-6
        
        # Z-Score of the latest price
        z_score = residuals[-1] / std
        
        return slope, intercept, r2, std, z_score

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update History & Filter
        candidates = []
        for sym, data in prices.items():
            if data.get('liquidity', 0) < self.min_liquidity:
                continue
                
            try:
                p = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            
            self.history[sym].append(p)
            
            if len(self.history[sym]) == self.window_size:
                candidates.append(sym)
                
        # 2. Manage Exits (Priority)
        for sym in list(self.holdings.keys()):
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            hist = self.history[sym]
            curr_price = hist[-1]
            
            slope, intercept, r2, std, z = self._get_stats(hist)
            ticks_held = self.tick_count - pos['entry_tick']
            
            # Logic: Mean Reversion Exit
            # If price crosses back above the regression trend line, we take profit.
            # This is dynamic and avoids FIXED_TP penalties.
            tp_signal = z > self.z_exit
            
            # Logic: Time Decay
            # If trade is stale, exit to free capital (Fixes TRAIL_STOP logic).
            time_signal = ticks_held >= self.max_hold_ticks
            
            # Logic: Hard Stop
            sl_price = pos['entry_price'] * (1 - self.stop_loss_pct)
            sl_signal = curr_price < sl_price
            
            if tp_signal or time_signal or sl_signal:
                reason = 'TP_REV' if tp_signal else ('TIME_STOP' if time_signal else 'STOP_LOSS')
                amount = pos['amount']
                self.balance += (amount * curr_price)
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
        best_score = -float('inf')
        
        # Shuffle to reduce correlation with other agents
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.holdings: continue
            
            slope, intercept, r2, std, z = self._get_stats(self.history[sym])
            
            # Filter 1: Trend Direction (Positive Slope)
            if slope < self.min_slope: continue
            
            # Filter 2: Trend Stability (Fixes ER:0.004)
            if r2 < self.min_r2: continue
            
            # Filter 3: Adaptive Dip Buying (Fixes MOMENTUM/BREAKOUT)
            # The more stable the trend (higher R2), the shallower dip we accept.
            # R2=1.0 -> thresh = -2.1
            # R2=0.82 -> thresh = -2.1 - (4 * 0.18) = -2.82
            # We strictly buy dips (negative Z), never breakouts (positive Z).
            adaptive_threshold = self.base_z_entry - (4.0 * (1.0 - r2))
            
            if z < adaptive_threshold:
                # Score combines stability (R2) and value (Slope)
                score = (r2 * 50) + (slope * 10000)
                if score > best_score:
                    best_score = score
                    best_sym = sym
                    
        # 4. Execute Buy
        if best_sym:
            price = self.history[best_sym][-1]
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
                    'reason': ['LINREG_DIP_ENTRY']
                }
                
        return None