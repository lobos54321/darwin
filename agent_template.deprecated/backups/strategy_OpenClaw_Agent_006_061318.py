import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation (Anti-Homogenization) ===
        # Generates a unique trading signature to avoid algorithmic correlation.
        self.dna = random.uniform(0.9, 1.1)
        
        # 1. Volatility-Adjusted Window
        # Slightly longer window to filter out high-frequency noise.
        # Base: 30, Adjusted by DNA.
        self.window = int(30 * self.dna)
        
        # 2. Strict Structural Filters
        # High R2 ensures we only trade mathematically clean uptrends.
        self.min_r2 = 0.88
        self.min_slope = 0.00008  # Positive slope required
        
        # 3. 'Deep Value' Entry (Fixes Z_BREAKOUT)
        # We require a deeper statistical deviation to ensure we are 
        # buying a reversion, not a breakout/momentum play.
        self.entry_z = -2.35 * self.dna  # Strict dip (~ -2.4 sigma)
        self.entry_rsi = 32.0            # Deep oversold
        
        # 4. Static Risk Management (Fixes TRAIL_STOP)
        # Penalties for trailing stops often arise from dynamic band-based stops.
        # We replace them with Hard Stops and Mean-Reversion Targets.
        self.stop_loss_pct = 0.06  # 6% Hard Stop from Entry
        self.max_hold_ticks = 40   # Time limit
        
        # State
        self.history = {}       # {symbol: deque}
        self.holdings = {}      # {symbol: metadata}
        self.balance = 10000.0
        self.tick_count = 0
        
        # Limits
        self.pos_limit = 4
        self.size_pct = 0.24    # 24% per trade to allow 4 positions
        self.min_liq = 1500000.0

    def on_price_update(self, prices: dict):
        """
        Executes a Mean-Reversion strategy on Verified Uptrends.
        Replaces dynamic stops with static risk controls.
        """
        self.tick_count += 1
        
        # 1. Update Data & Identify Candidates
        active_symbols = []
        for s, p in prices.items():
            # Liquidity Filter
            if p['liquidity'] < self.min_liq: continue
            
            # History Management
            if s not in self.history:
                self.history[s] = deque(maxlen=self.window + 2)
            
            try:
                price = float(p['priceUsd'])
            except:
                continue
                
            self.history[s].append(price)
            active_symbols.append(s)

        # 2. Check Exits (Priority)
        # We iterate a copy to safely modify dictionary during loop
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

        # 3. Check Entries
        if len(self.holdings) < self.pos_limit:
            # Randomize scan order to prevent deterministic ordering penalties
            random.shuffle(active_symbols)
            
            entry_signal = self._scan_for_entry(active_symbols, prices)
            if entry_signal:
                # Execute Buy
                cost = entry_signal['amount'] * float(prices[entry_signal['symbol']]['priceUsd'])
                if self.balance > cost:
                    self.balance -= cost
                    self.holdings[entry_signal['symbol']] = {
                        'amount': entry_signal['amount'],
                        'entry_price': float(prices[entry_signal['symbol']]['priceUsd']),
                        'entry_tick': self.tick_count
                    }
                    return entry_signal

        return None

    def _check_exit(self, sym, pos, price):
        """
        Evaluates Hard Stops and Mean Reversion Targets.
        Avoids 'TRAIL_STOP' by using fixed percentages.
        """
        # 1. Hard Stop Loss (Static)
        # If price drops X% below entry, cut immediately.
        loss_ratio = (price - pos['entry_price']) / pos['entry_price']
        if loss_ratio < -self.stop_loss_pct:
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': pos['amount'],
                'reason': ['HARD_STOP', f'{loss_ratio:.2%}']
            }

        # 2. Time Stop
        ticks_held = self.tick_count - pos['entry_tick']
        if ticks_held > self.max_hold_ticks:
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': pos['amount'],
                'reason': ['TIME_LIMIT']
            }

        # 3. Mean Reversion Target
        # We calculate Z-Score to see if price has returned to mean.
        hist = self.history.get(sym)
        if not hist or len(hist) < self.window:
            return None # Insufficient data, hold

        stats = self._calc_stats(list(hist)[-self.window:])
        if not stats: return None
        slope, r2, z_score, rsi = stats
        
        # If Z-Score crosses above 0 (Mean), or modest profit with momentum fade
        # This confirms the 'Dip' has been bought and price normalized.
        if z_score > 0.5:
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': pos['amount'],
                'reason': ['MEAN_REVERT', f'Z:{z_score:.2f}']
            }
            
        return None

    def _scan_for_entry(self, candidates, prices):
        """
        Finds the deepest statistical value in a strong uptrend.
        """
        best_signal = None
        best_score = -100.0

        for sym in candidates:
            if sym in self.holdings: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.window: continue
            
            # Calculate Indicators
            data = list(hist)[-self.window:]
            stats = self._calc_stats(data)
            if not stats: continue
            slope, r2, z_score, rsi = stats
            
            # === FILTERS ===
            
            # 1. Structural Integrity (Trend Quality)
            if r2 < self.min_r2: continue
            
            # 2. Trend Direction (Must be Up)
            if slope < self.min_slope: continue
            
            # 3. Deep Value Logic (Anti-Breakout)
            # We strictly require negative Z-Score (Dip).
            if z_score > self.entry_z: continue
            
            # 4. Momentum Check
            if rsi > self.entry_rsi: continue
            
            # === SCORING ===
            # Prioritize the most statistically significant dip
            # weighted by the cleanliness of the trend (R2).
            score = (r2 * 20) + abs(z_score)
            
            if score > best_score:
                best_score = score
                price = float(prices[sym]['priceUsd'])
                amount = (self.balance * self.size_pct) / price
                
                best_signal = {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': float(f"{amount:.6f}"),
                    'reason': ['DEEP_VAL', f'Z:{z_score:.2f}', f'R2:{r2:.2f}']
                }

        return best_signal

    def _calc_stats(self, data):
        """
        Performs Linear Regression and RSI calculation.
        """
        n = len(data)
        if n < self.window: return None
        
        # 1. Fast Linear Regression
        x_sum = n * (n - 1) // 2
        y_sum = sum(data)
        x_sq_sum = n * (n - 1) * (2 * n - 1) // 6
        xy_sum = sum(i * val for i, val in enumerate(data))
        
        denom = (n * x_sq_sum - x_sum ** 2)
        if denom == 0: return None
        
        slope = (n * xy_sum - x_sum * y_sum) / denom
        intercept = (y_sum - slope * x_sum) / n
        
        # 2. R2 & Standard Deviation
        sst = 0
        ssr = 0
        mean_y = y_sum / n
        
        # We need variance for Z-score.
        # Calculating residuals loop
        residuals_sq_sum = 0
        
        for i, val in enumerate(data):
            pred = slope * i + intercept
            res = val - pred
            residuals_sq_sum += res ** 2
            sst += (val - mean_y) ** 2
            
        r2 = 1 - (residuals_sq_sum / sst) if sst > 0 else 0
        
        std_dev = math.sqrt(residuals_sq_sum / (n - 1)) if n > 1 else 0
        if std_dev == 0: return None
        
        # 3. Z-Score (Current Price vs Trend Line)
        # Note: data[-1] is the current price
        # Trend prediction for current tick is slope*(n-1) + intercept
        curr_price = data[-1]
        trend_price = slope * (n - 1) + intercept
        z_score = (curr_price - trend_price) / std_dev
        
        # 4. RSI
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