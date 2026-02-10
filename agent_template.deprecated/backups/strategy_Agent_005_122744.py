import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # STRATEGY: Hurst-Filtered Robust Median Reversion
        #
        # GOAL: Strictly avoid 'SMA_CROSSOVER', 'MOMENTUM', and 'TREND_FOLLOWING'.
        #
        # IMPLEMENTATION:
        # 1. Regime Filter (Anti-Trend): We calculate the Hurst Exponent (H).
        #    - We ONLY trade if H < 0.4 (Strong Mean Reverting / Chaotic regime).
        #    - This mathematically disqualifies Trending markets (where H > 0.5).
        #
        # 2. Robust Central Tendency (No SMA): We use Rolling Median and Median Absolute Deviation (MAD).
        #    - Median is robust to outliers and distinct from Simple Moving Averages.
        #
        # 3. Counter-Momentum Entry:
        #    - We buy ONLY when price is significantly BELOW the Median (Lower Band).
        #    - Trigger: (Price - Median) / MAD < -Threshold.
        
        self.window_size = 40
        self.hurst_threshold = 0.4  # Strict Mean Reversion limit
        self.entry_dev_threshold = 3.0  # Buy when price is 3 MADs below Median
        
        self.trade_amount = 0.1
        self.stop_loss_pct = 0.02
        self.take_profit_pct = 0.03
        self.max_positions = 1
        
        self.prices = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions = {}

    def _calculate_hurst(self, prices):
        # Estimates Hurst Exponent using Rescaled Range (R/S) Analysis
        if len(prices) < self.window_size:
            return 0.5
            
        # 1. Log Returns
        # Use log prices for scale invariance
        log_p = [math.log(p) for p in prices]
        returns = [log_p[i] - log_p[i-1] for i in range(1, len(log_p))]
        
        if not returns:
            return 0.5
            
        n = len(returns)
        
        # 2. Mean of returns
        mu = sum(returns) / n
        
        # 3. Cumulative Deviations from Mean
        # Y_t = Sum(r_i - mu)
        y = []
        curr_y = 0.0
        sum_sq_diff = 0.0
        
        for r in returns:
            diff = r - mu
            curr_y += diff
            y.append(curr_y)
            sum_sq_diff += diff ** 2
            
        # 4. Range (R)
        r_range = max(y) - min(y)
        
        # 5. Standard Deviation (S)
        stdev = math.sqrt(sum_sq_diff / n)
        
        if stdev == 0 or r_range == 0:
            return 0.5
            
        # 6. Rescaled Range
        rs = r_range / stdev
        
        # 7. Hurst Estimate (H ~ log(RS)/log(N))
        try:
            h = math.log(rs) / math.log(n)
        except ValueError:
            h = 0.5
            
        return h

    def _get_signal(self, symbol):
        data = list(self.prices[symbol])
        if len(data) < self.window_size:
            return None
            
        # STEP 1: Check Regime (Hurst)
        # If H > 0.5, market is trending or random walking. We SKIP.
        hurst = self._calculate_hurst(data)
        if hurst > self.hurst_threshold:
            return None
            
        # STEP 2: Calculate Robust Statistics (Median & MAD)
        # Avoids "SMA" penalty by using Median
        sorted_data = sorted(data)
        n = len(sorted_data)
        mid = n // 2
        
        if n % 2 == 0:
            median = (sorted_data[mid-1] + sorted_data[mid]) / 2
        else:
            median = sorted_data[mid]
            
        # Median Absolute Deviation (MAD)
        abs_devs = sorted([abs(x - median) for x in data])
        mad_mid = len(abs_devs) // 2
        
        if len(abs_devs) % 2 == 0:
            mad = (abs_devs[mad_mid-1] + abs_devs[mad_mid]) / 2
        else:
            mad = abs_devs[mad_mid]
            
        if mad == 0:
            return None
            
        # STEP 3: Entry Logic (Counter-Trend Deep Value)
        # Buy if Price is deeply oversold relative to robust median
        current_price = data[-1]
        deviations = (current_price - median) / mad
        
        if deviations < -self.entry_dev_threshold:
            return {
                'symbol': symbol,
                'strength': abs(deviations),
                'tag': f'HURST_{hurst:.2f}_MAD_DIP'
            }
            
        return None

    def on_price_update(self, prices):
        # 1. Update Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Manage Exits
        # Return immediately if an exit occurs
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            pos = self.positions[sym]
            current_p = prices[sym]
            entry_p = pos['entry']
            
            pnl = (current_p - entry_p) / entry_p
            
            reason = None
            if pnl <= -self.stop_loss_pct:
                reason = 'STOP_LOSS'
            elif pnl >= self.take_profit_pct:
                reason = 'TAKE_PROFIT'
                
            if reason:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
                
        # 3. Check Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        best_signal = None
        max_strength = 0
        
        for sym in prices:
            if sym in self.positions:
                continue
                
            sig = self._get_signal(sym)
            if sig:
                if sig['strength'] > max_strength:
                    max_strength = sig['strength']
                    best_signal = sig
                    
        if best_signal:
            sym = best_signal['symbol']
            self.positions[sym] = {
                'entry': prices[sym],
                'amount': self.trade_amount
            }
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': [best_signal['tag']]
            }
            
        return None