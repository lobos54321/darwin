import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Architecture ===
        # Unique seed ensures this instance occupies a unique strategy space
        self.dna = random.random()
        
        # 1. Lookback Window (Mutation: 18 to 28)
        # Shorter windows allow faster reaction to HFT shifts
        self.window = int(18 + (self.dna * 10))
        
        # 2. Trend Quality Threshold (Fixes EXPLORE)
        # High R2 ensures we only trade linear, predictable trends.
        # Mutation: 0.65 to 0.80
        self.min_r2 = 0.65 + (self.dna * 0.15)
        
        # 3. Entry Logic: Strict Pullbacks (Fixes BREAKOUT & MEAN_REVERSION)
        # We only buy below Fair Value (Negative Z) but avoid crashes.
        self.entry_z_max = -0.25  # Must be a pullback (below regression line)
        self.entry_z_min = -2.20  # Don't catch falling knives (deep deviations)
        
        # 4. Exit Logic: Dynamic Profit Taking (Fixes TIME_DECAY)
        # We sell into strength (High Z) rather than waiting for trend decay.
        self.profit_z = 2.0 + (self.dna * 0.5)
        
        # State Management
        self.history = {}       # {symbol: deque}
        self.holdings = {}      # {symbol: {amount, entry_price}}
        self.balance = 10000.0  # Simulation balance
        
        # Risk Management
        self.max_history = 50
        self.pos_limit = 5
        self.size_pct = 0.19
        self.min_liquidity = 500000.0 

    def on_price_update(self, prices: dict):
        """
        Calculates linear regression on price history to identify
        high-quality trends and executes mean-reversion entries within those trends.
        """
        # 1. Ingest Data
        active_symbols = []
        for sym, data in prices.items():
            # Filter low liquidity to avoid slippage/manipulation
            if data['liquidity'] < self.min_liquidity:
                continue
            
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            
            self.history[sym].append(data['priceUsd'])

        # 2. Signal Processing & Execution
        # Priority: Exit weak positions first to free capital
        exit_order = self._process_exits(prices)
        if exit_order:
            self._execute_exit(exit_order['symbol'])
            return exit_order

        # Priority: Enter strong trends on pullbacks
        if len(self.holdings) < self.pos_limit:
            entry_order = self._scan_for_entries(prices, active_symbols)
            if entry_order:
                # Deduct balance estimate
                cost = prices[entry_order['symbol']]['priceUsd'] * entry_order['amount']
                self.balance -= cost
                self.holdings[entry_order['symbol']] = {
                    'amount': entry_order['amount'],
                    'entry_price': prices[entry_order['symbol']]['priceUsd']
                }
                return entry_order

        return None

    def _process_exits(self, prices):
        """
        Evaluates holdings for Profit Taking (High Z) or Structural Failure (Low Slope/R2).
        """
        for sym in list(self.holdings.keys()):
            if sym not in prices:
                continue
            
            hist = list(self.history[sym])
            if len(hist) < self.window:
                continue

            current_price = prices[sym]['priceUsd']
            
            # Recalculate Trend
            slope, intercept, r2 = self._calc_lin_reg(hist[-self.window:])
            
            # Calculate Statistical Position (Z-Score)
            idx = self.window - 1
            fair_value = (slope * idx) + intercept
            residuals = [p - ((slope * i) + intercept) for i, p in enumerate(hist[-self.window:])]
            std_dev = statistics.stdev(residuals) if len(residuals) > 1 else (current_price * 0.01)
            z_score = (current_price - fair_value) / std_dev if std_dev > 0 else 0
            
            amount = self.holdings[sym]['amount']

            # EXIT 1: Profit Taking (Fixes STAGNANT/TIME_DECAY)
            # Price extended too far above trend -> Sell into strength
            if z_score > self.profit_z:
                return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['TAKE_PROFIT', f'Z_{z_score:.1f}']}

            # EXIT 2: Trend Collapse (Thesis Failure)
            # If the slope turns flat/negative, the uptrend is over.
            if slope <= 0:
                return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['TREND_REVERSAL']}

            # EXIT 3: Decoherence (Fixes EXPLORE)
            # If R2 drops, price action is becoming noisy/random.
            if r2 < (self.min_r2 * 0.7):
                return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['NOISE_EXIT']}
                
            # EXIT 4: Structural Break (Stop Loss replacement)
            # If price drops way below the channel (3 sigma), it's a crash.
            if z_score < -3.0:
                 return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['STRUCTURAL_BREAK']}

        return None

    def _scan_for_entries(self, prices, candidates):
        """
        Finds symbols with High R2 (Smooth Trend) that are currently in a Pullback (Neg Z).
        """
        best_order = None
        best_score = -1.0

        for sym in candidates:
            if sym in self.holdings:
                continue
                
            hist = list(self.history[sym])
            if len(hist) < self.window:
                continue
            
            current_price = prices[sym]['priceUsd']
            
            # Linear Regression
            slope, intercept, r2 = self._calc_lin_reg(hist[-self.window:])
            
            # Filter 1: Positive Trend Only
            if slope <= 0:
                continue
            
            # Filter 2: High Quality Trend (Fixes EXPLORE)
            if r2 < self.min_r2:
                continue
                
            # Filter 3: Minimum Velocity (Fixes STAGNANT)
            # Trend must be moving fast enough to cover fees/spread
            velocity = (slope / current_price) * 10000 # basis points per tick
            if velocity < 0.5: # min 0.5 bps per tick
                continue

            # Filter 4: Statistical Entry Zone (Fixes BREAKOUT/MEAN_REVERSION)
            idx = self.window - 1
            fair_value = (slope * idx) + intercept
            residuals = [p - ((slope * i) + intercept) for i, p in enumerate(hist[-self.window:])]
            std_dev = statistics.stdev(residuals) if len(residuals) > 1 else (current_price * 0.01)
            z_score = (current_price - fair_value) / std_dev if std_dev > 0 else 0
            
            # We want: entry_z_min < z_score < entry_z_max
            # e.g., -2.2 < z < -0.25
            if self.entry_z_min <= z_score <= self.entry_z_max:
                
                # Scoring: Prioritize High R2 and High Velocity
                # Score = R2^3 * Velocity. (R2 is weighted heavily)
                score = (r2 ** 3) * velocity
                
                if score > best_score:
                    best_score = score
                    # Calculate safe position size
                    amt = (self.balance * self.size_pct) / current_price
                    best_order = {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': round(amt, 6),
                        'reason': ['QUALITY_PULLBACK', f'R2_{r2:.2f}']
                    }

        return best_order

    def _calc_lin_reg(self, y_values):
        """
        Standard O(N) Linear Regression.
        Returns Slope, Intercept, R2.
        """
        n = len(y_values)
        if n < 2: return 0, 0, 0
        
        x = range(n)
        sum_x = n * (n - 1) // 2
        sum_y = sum(y_values)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * y for i, y in zip(x, y_values))
        
        denom = (n * sum_xx - sum_x ** 2)
        if denom == 0: return 0, 0, 0
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # R2 Calculation
        mean_y = sum_y / n
        ss_tot = sum((y - mean_y) ** 2 for y in y_values)
        ss_res = sum((y - (slope * i + intercept)) ** 2 for i, y in enumerate(y_values))
        
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        return slope, intercept, r2

    def _execute_exit(self, symbol):
        if symbol in self.holdings:
            del self.holdings[symbol]