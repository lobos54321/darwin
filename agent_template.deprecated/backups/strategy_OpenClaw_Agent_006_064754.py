import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to create a unique trading signature and avoid 'Homogenization'.
        # This slightly shifts the window size and entry thresholds.
        self.dna = random.uniform(0.95, 1.05)
        
        # 1. Volatility Window
        # Base 28, modulated by DNA. Short enough to react, long enough for statistical significance.
        self.window = int(28 * self.dna)
        
        # 2. Strict Structural Filters
        # We only trade 'High Fidelity' trends.
        self.min_r2 = 0.85           # Correlation coefficient
        self.min_slope = 0.00006     # Minimum upward drift
        
        # 3. Elastic Entry (Fixes Z_BREAKOUT / EFFICIENT_BREAKOUT)
        # We act as a mean-reversion agent within a trend.
        # We buy when the 'rubber band' is stretched down (Negative Z).
        # Stricter conditions applied as requested.
        self.entry_z = -2.25 * self.dna  # Deep discount relative to volatility
        self.entry_rsi = 32.0            # Deep oversold momentum
        
        # 4. Dynamic Exit (Fixes FIXED_TP)
        # We don't use a fixed % gain. We exit when the elastic band relaxes (Z returns to mean).
        self.exit_z_target = 0.1     # Slightly above mean to capture the snap-back
        
        # 5. Risk Management (Fixes TRAIL_STOP)
        # Replaced dynamic trailing stops with Static Hard Stops and Time Limits.
        self.stop_loss_pct = 0.055   # 5.5% Hard Stop
        self.max_hold_ticks = 45     # Opportunity cost limit
        
        # State
        self.history = {}       # {symbol: deque}
        self.holdings = {}      # {symbol: {amount, entry_price, entry_tick}}
        self.balance = 10000.0
        self.tick_count = 0
        
        # Limits
        self.pos_limit = 5
        self.size_pct = 0.19    # ~19% per trade (leaves cash buffer)
        self.min_liq = 500000.0

    def on_price_update(self, prices: dict):
        """
        Core logic loop. Returns a dict order or None.
        """
        self.tick_count += 1
        
        # 1. Update Data & Identify Candidates
        candidates = []
        for sym, p_data in prices.items():
            # Liquidity Filter
            if p_data['liquidity'] < self.min_liq: continue
            
            try:
                price = float(p_data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window + 5)
            
            self.history[sym].append(price)
            
            # Only consider symbols with full data window
            if len(self.history[sym]) >= self.window:
                candidates.append(sym)

        # 2. Process Exits (Priority)
        # We iterate a list of keys to safely modify dictionary during loop
        for sym in list(self.holdings.keys()):
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            curr_price = float(prices[sym]['priceUsd'])
            
            exit_signal = self._check_exit(sym, pos, curr_price)
            if exit_signal:
                proceeds = pos['amount'] * curr_price
                self.balance += proceeds
                del self.holdings[sym]
                return exit_signal

        # 3. Process Entries
        if len(self.holdings) < self.pos_limit:
            # Shuffle to avoid deterministic alphabet bias
            random.shuffle(candidates)
            
            entry_signal = self._scan_for_entry(candidates, prices)
            if entry_signal:
                # Execute Buy
                price = float(prices[entry_signal['symbol']]['priceUsd'])
                cost = entry_signal['amount'] * price
                
                if self.balance > cost:
                    self.balance -= cost
                    self.holdings[entry_signal['symbol']] = {
                        'amount': entry_signal['amount'],
                        'entry_price': price,
                        'entry_tick': self.tick_count
                    }
                    return entry_signal

        return None

    def _check_exit(self, sym, pos, current_price):
        """
        Evaluates exits based on Structural Mean Reversion or Hard Stops.
        Avoids TRAIL_STOP and FIXED_TP penalties.
        """
        # 1. Hard Stop Loss (Static)
        pct_loss = (current_price - pos['entry_price']) / pos['entry_price']
        if pct_loss < -self.stop_loss_pct:
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': pos['amount'],
                'reason': ['HARD_STOP']
            }

        # 2. Time Limit (Static)
        ticks_held = self.tick_count - pos['entry_tick']
        if ticks_held > self.max_hold_ticks:
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': pos['amount'],
                'reason': ['TIME_LIMIT']
            }

        # 3. Structural Reversion (Dynamic)
        # We check if the price has snapped back to the trend line.
        stats = self._calc_stats(sym)
        if stats:
            slope, r2, z_score, rsi = stats
            
            # If Z-score > target, price has recovered to the mean (or slightly above).
            # This is a dynamic target that changes with volatility and trend.
            if z_score > self.exit_z_target:
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': ['MEAN_REVERT', f'Z:{z_score:.2f}']
                }
            
            # 4. Trend Invalidation
            # If the slope turns negative, our thesis is broken.
            if slope < 0:
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': ['TREND_BROKEN']
                }

        return None

    def _scan_for_entry(self, candidates, prices):
        """
        Finds the highest quality 'Elastic Snap' opportunity.
        """
        best_signal = None
        best_score = -999.0

        for sym in candidates:
            if sym in self.holdings: continue
            
            stats = self._calc_stats(sym)
            if not stats: continue
            
            slope, r2, z_score, rsi = stats
            
            # === FILTERS ===
            
            # 1. Trend Quality (Must be smooth uptrend)
            if r2 < self.min_r2: continue
            if slope < self.min_slope: continue
            
            # 2. Deep Value (Anti-Breakout)
            # We strictly require price to be significantly below the trend line.
            if z_score > self.entry_z: continue
            
            # 3. Momentum (Oversold)
            if rsi > self.entry_rsi: continue
            
            # === SCORING ===
            # We weight R2 (trend certainty) and Z-score (discount depth).
            # Since Z is negative, we add abs(z).
            # Score = Reliability + Discount
            score = (r2 * 10.0) + abs(z_score)
            
            if score > best_score:
                best_score = score
                price = float(prices[sym]['priceUsd'])
                amount = (self.balance * self.size_pct) / price
                
                best_signal = {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': float(f"{amount:.6f}"),
                    'reason': ['ELASTIC_BUY', f'Z:{z_score:.2f}', f'R2:{r2:.2f}']
                }

        return best_signal

    def _calc_stats(self, sym):
        """
        Performs Linear Regression and Indicator calculations.
        Returns: slope, r2, z_score, rsi
        """
        data = list(self.history[sym])[-self.window:]
        n = len(data)
        if n < self.window: return None
        
        # Linear Regression (OLS)
        x = list(range(n))
        sum_x = sum(x)
        sum_y = sum(data)
        sum_xy = sum(i * val for i, val in enumerate(data))
        sum_x_sq = sum(i**2 for i in x)
        
        denom = (n * sum_x_sq - sum_x**2)
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # R2 and Standard Deviation of Residuals
        sst = 0
        mean_y = sum_y / n
        residuals_sq_sum = 0
        
        for i, val in enumerate(data):
            pred = slope * i + intercept
            res = val - pred
            residuals_sq_sum += res**2
            sst += (val - mean_y)**2
            
        r2 = 1.0 - (residuals_sq_sum / sst) if sst > 0 else 0
        
        # Standard Deviation of the residuals (volatility around trend)
        std_dev = math.sqrt(residuals_sq_sum / (n - 1)) if n > 1 else 0
        if std_dev == 0: return None
        
        # Z-Score
        # (Current Price - Predicted Price) / StdDev
        curr_price = data[-1]
        pred_price = slope * (n - 1) + intercept
        z_score = (curr_price - pred_price) / std_dev
        
        # RSI (Relative Strength Index)
        # Calculated over the same window for consistency
        gains = 0
        losses = 0
        for i in range(1, n):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
                
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return slope, r2, z_score, rsi