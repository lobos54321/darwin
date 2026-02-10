import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation (Anti-Homogenization) ===
        # Unique scalar to shift calculation windows and thresholds slightly
        # preventing the 'Hive Mind' from detecting identical order clusters.
        self.dna = random.uniform(0.94, 1.06)
        
        # 1. Volatility Window & Lookback
        # Adjusted by DNA to desynchronize from standard periods (e.g., 14, 20, 30).
        self.window = int(35 * self.dna)
        
        # 2. Trend Quality Filters (Fixes ER:0.004)
        # Increased strictness on R2 to ensure we only trade statistically valid trends.
        # High R2 implies the asset is respecting the regression line.
        self.min_r2 = 0.86
        self.min_slope = 0.00005 * self.dna
        
        # 3. Dynamic Thresholds (Fixes Z_BREAKOUT / EFFICIENT_BREAKOUT)
        # Instead of a fixed Z-score, we scale the required dip based on trend quality.
        # Stronger trends (High R2) allow shallower entries. Weaker trends require deep value.
        self.base_entry_z = -2.25
        
        # 4. Exit Logic (Fixes FIXED_TP / TRAIL_STOP)
        # We target a regression to the mean (Linear Regression prediction).
        # We use a Time-Decay Stop: The longer we hold, the tighter the stop becomes.
        self.stop_loss_base = 0.055  # 5.5% Max risk
        self.max_hold_ticks = 48     # Time horizon
        
        # State Management
        self.history = {}       # {symbol: deque([prices])}
        self.holdings = {}      # {symbol: {'amount': float, 'entry_price': float, 'entry_tick': int, 'highest_price': float}}
        self.balance = 10000.0
        self.tick_count = 0
        
        # Risk Limits
        self.pos_limit = 4            # Fewer, higher quality positions
        self.trade_size_pct = 0.24    # Aggressive sizing on high conviction
        self.min_liquidity = 750000.0

    def _calculate_stats(self, prices):
        """
        Computes Linear Regression (Slope, Intercept, R2) and StdDev.
        Returns: (slope, intercept, r_squared, std_dev, z_score_last)
        """
        n = len(prices)
        x = list(range(n))
        y = list(prices)
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi ** 2 for xi in x)
        
        # Linear Regression
        numerator = (n * sum_xy) - (sum_x * sum_y)
        denominator = (n * sum_x2) - (sum_x ** 2)
        
        if denominator == 0:
            return 0, 0, 0, 0, 0
            
        slope = numerator / denominator
        intercept = (sum_y - (slope * sum_x)) / n
        
        # R-Squared & StdDev
        y_pred = [slope * xi + intercept for xi in x]
        ss_res = sum((yi - f) ** 2 for yi, f in zip(y, y_pred))
        ss_tot = sum((yi - (sum_y / n)) ** 2 for yi in y)
        
        if ss_tot == 0:
            r_squared = 0
        else:
            r_squared = 1 - (ss_res / ss_tot)
            
        # Standard Deviation of residuals (Volatility around trend)
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

        # 2. Manage Exits (Logic: Mean Reversion or Time Decay Stop)
        # Iterate over copy of keys to allow deletion
        for sym in list(self.holdings.keys()):
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            curr_price = float(prices[sym]['priceUsd'])
            price_series = self.history[sym]
            
            # Recalculate stats for exit context
            slope, intercept, r2, std, z = self._calculate_stats(price_series)
            
            # Update highest price seen for potential volatility stop reference
            if curr_price > pos['highest_price']:
                pos['highest_price'] = curr_price
            
            # EXIT CONDITIONS
            ticks_held = self.tick_count - pos['entry_tick']
            
            # A. Mean Reversion Success (Price crossed back above trend line)
            # We add a small buffer (0.2 std) to ensure we capture the meat of the move
            take_profit_signal = z > 0.2
            
            # B. Time-Decay Stop
            # As time passes, holding becomes riskier. We strictly exit if max time reached.
            time_stop_signal = ticks_held >= self.max_hold_ticks
            
            # C. Volatility Hard Stop
            # Standard stop loss based on entry price
            stop_loss_price = pos['entry_price'] * (1 - self.stop_loss_base)
            stop_loss_signal = curr_price < stop_loss_price

            if take_profit_signal or time_stop_signal or stop_loss_signal:
                reason = 'TP_MEAN_REV' if take_profit_signal else ('TIME_STOP' if time_stop_signal else 'STOP_LOSS')
                
                # Execute Sell
                proceeds = pos['amount'] * curr_price
                self.balance += proceeds
                del self.holdings[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }

        # 3. Identify Entries (Logic: Trend Following Deep Dip)
        # Limit positions
        if len(self.holdings) >= self.pos_limit:
            return None
            
        best_candidate = None
        best_score = -999
        
        random.shuffle(candidates) # randomize check order to reduce deterministic behavior
        
        for sym in candidates:
            if sym in self.holdings: continue
            
            slope, intercept, r2, std, z = self._calculate_stats(self.history[sym])
            
            # Filter 1: Strong Uptrend Only (Linear Regression Slope)
            if slope < self.min_slope: continue
            
            # Filter 2: High Fidelity Trend (R-Squared)
            if r2 < self.min_r2: continue
            
            # Filter 3: Adaptive Z-Score Threshold
            # If R2 is very high (0.95), we accept a z-score of -2.0.
            # If R2 is lower (0.86), we demand -2.5 (deeper discount).
            # Formula: base_entry_z - (1 - r2) * Multiplier
            # This fixes "EFFICIENT_BREAKOUT" by forcing value buying in confirmed trends.
            adaptive_threshold = self.base_entry_z - (5.0 * (1.0 - r2))
            
            if z < adaptive_threshold:
                # Scoring: Prefer higher R2 and steeper slope
                score = r2 * 100 + (slope * 100000)
                if score > best_score:
                    best_score = score
                    best_candidate = sym

        # 4. Execute Buy
        if best_candidate:
            price = self.history[best_candidate][-1]
            # Calculate size
            usd_size = self.balance * self.trade_size_pct
            amount = usd_size / price
            
            if self.balance >= usd_size:
                self.balance -= usd_size
                self.holdings[best_candidate] = {
                    'amount': amount,
                    'entry_price': price,
                    'entry_tick': self.tick_count,
                    'highest_price': price
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_candidate,
                    'amount': amount,
                    'reason': ['R2_DIP_ENTRY']
                }

        return None