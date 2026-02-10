import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic & Strategic Architecture ===
        # Unique seed to ensure heterogeneous strategy behavior
        self.dna = random.random()
        
        # 1. Dynamic Lookback Window
        # Shorter windows (20-30) for HFT responsiveness, modulated by DNA.
        self.window = int(20 + (self.dna * 10))
        
        # 2. Strict Trend Definition (Fixes EXPLORE & NOISE)
        # R-Squared must be extremely high (>0.75) to confirm a "Pipe" formation.
        # We only trade deterministic trends, not random walks.
        self.min_r2 = 0.75 + (self.dna * 0.1)
        
        # 3. Surgical Entry Logic (Fixes MEAN_REVERSION & BREAKOUT)
        # We only buy pullbacks within a defined Standard Deviation channel.
        # Upper: Must be a discount (-0.5 sigma).
        # Lower: Must NOT be a crash (-2.0 sigma). Avoids "Catching Knives".
        self.entry_z_upper = -0.5
        self.entry_z_lower = -2.0
        
        # 4. Momentum Velocity (Fixes STAGNANT)
        # Minimum basis points per tick slope to justify capital lock-up.
        self.min_velocity = 0.0001 # 0.01% price increase per tick avg
        
        # 5. Dynamic Exit Logic (Fixes TIME_DECAY)
        # Target Z-Score for profit, decays over time to force capital rotation.
        self.base_exit_z = 1.5 + (self.dna * 0.5)
        
        # State Management
        self.history = {}       # {symbol: deque}
        self.holdings = {}      # {symbol: {'amount': float, 'entry_tick': int}}
        self.balance = 10000.0  # Simulation balance
        self.tick_count = 0
        
        # Risk Management
        self.pos_limit = 5
        self.size_pct = 0.19    # ~20% allocation per trade
        self.min_liquidity = 750000.0 

    def on_price_update(self, prices: dict):
        """
        Executes a Statistical Regression Channel strategy.
        Identifies high-confidence linear uptrends (High R2) and enters
        on statistical deviations (Negative Z-Score) to capture mean reversion
        aligned with the primary trend.
        """
        self.tick_count += 1
        
        # 1. Data Ingestion & Hygiene
        active_symbols = []
        for sym, data in prices.items():
            # Filter for liquidity to ensure trade execution quality
            if data['liquidity'] < self.min_liquidity:
                continue
            
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window + 5)
            
            self.history[sym].append(data['priceUsd'])

        # 2. Priority: Process Exits
        # Check existing positions for profit targets or thesis failures
        exit_order = self._process_exits(prices)
        if exit_order:
            self._execute_exit(exit_order['symbol'])
            return exit_order

        # 3. Priority: Scan for Entries
        # If we have capital, look for high-quality pullbacks
        if len(self.holdings) < self.pos_limit:
            entry_order = self._scan_entries(prices, active_symbols)
            if entry_order:
                # Update simulated balance and holdings
                cost = prices[entry_order['symbol']]['priceUsd'] * entry_order['amount']
                if self.balance > cost:
                    self.balance -= cost
                    self.holdings[entry_order['symbol']] = {
                        'amount': entry_order['amount'],
                        'entry_price': prices[entry_order['symbol']]['priceUsd'],
                        'entry_tick': self.tick_count
                    }
                    return entry_order

        return None

    def _process_exits(self, prices):
        """
        Evaluates positions for Z-Score targets, Trend Breakdown, or Time Decay.
        """
        for sym, pos in self.holdings.items():
            if sym not in prices:
                continue
                
            hist = self.history[sym]
            if len(hist) < self.window:
                continue

            current_price = prices[sym]['priceUsd']
            
            # Calculate Regression Stats
            slope, intercept, r2, std_dev = self._calc_regression_stats(list(hist)[-self.window:])
            
            # Calculate Current Z-Score
            idx = self.window - 1
            fair_value = (slope * idx) + intercept
            z_score = (current_price - fair_value) / std_dev if std_dev > 0 else 0
            
            amount = pos['amount']

            # EXIT CONDITION 1: Trend Reversal (Safety)
            # If the slope turns negative, the uptrend thesis is invalid.
            if slope <= 0:
                return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['TREND_REVERSAL']}

            # EXIT CONDITION 2: Structural Break (Stop Loss)
            # If price deviates > 3.5 sigma down, it's a black swan/crash event.
            if z_score < -3.5:
                 return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['STRUCTURAL_BREAK']}

            # EXIT CONDITION 3: Dynamic Profit Taking (Fixes TIME_DECAY)
            # If we hold too long without result, lower the profit target to exit.
            ticks_held = self.tick_count - pos['entry_tick']
            target_z = self.base_exit_z
            
            # Decay target after 25 ticks to free capital
            if ticks_held > 25:
                target_z *= 0.6
                
            if z_score > target_z:
                return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['TAKE_PROFIT', f'Z_{z_score:.1f}']}

            # EXIT CONDITION 4: Decoherence
            # If the trend becomes messy (low R2), exit to avoid random walk behavior.
            if r2 < (self.min_r2 * 0.8):
                return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['NOISE_EXIT']}

        return None

    def _scan_entries(self, prices, candidates):
        """
        Finds the statistically best entry: High R2, Positive Slope, Negative Z-Score.
        """
        best_order = None
        best_score = -1.0

        for sym in candidates:
            if sym in self.holdings:
                continue
                
            hist = self.history[sym]
            if len(hist) < self.window:
                continue
            
            current_price = prices[sym]['priceUsd']
            
            # Calculate Regression
            slope, intercept, r2, std_dev = self._calc_regression_stats(list(hist)[-self.window:])
            
            # Filter 1: Strong Uptrend Only (Avoids Counter-Trend Mean Reversion)
            if slope <= 0:
                continue
            
            # Filter 2: High Predictability (Fixes EXPLORE)
            if r2 < self.min_r2:
                continue
                
            # Filter 3: Minimum Velocity (Fixes STAGNANT)
            # Check relative velocity (slope / price)
            velocity = slope / current_price
            if velocity < self.min_velocity:
                continue

            # Filter 4: Statistical Buy Zone
            idx = self.window - 1
            fair_value = (slope * idx) + intercept
            
            # Prevent Division by Zero
            if std_dev == 0:
                continue
                
            z_score = (current_price - fair_value) / std_dev
            
            # We look for a dip (z < -0.5) but not a crash (z > -2.0)
            if self.entry_z_lower <= z_score <= self.entry_z_upper:
                
                # Scoring: Prioritize "Smoothness" (R2) over Magnitude.
                # A smooth trend is safer than a volatile one.
                # Score = R2^4 * DistanceFromUpper
                score = (r2 ** 4) * (self.entry_z_upper - z_score)
                
                if score > best_score:
                    best_score = score
                    # Position Sizing
                    amt = (self.balance * self.size_pct) / current_price
                    best_order = {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': round(amt, 6),
                        'reason': ['REGRESSION_PULLBACK', f'R2_{r2:.2f}']
                    }

        return best_order

    def _calc_regression_stats(self, y_values):
        """
        O(N) Calculation of Slope, Intercept, R2, and StdDev.
        """
        n = len(y_values)
        if n < 2: return 0, 0, 0, 0
        
        x = range(n)
        sum_x = n * (n - 1) // 2
        sum_y = sum(y_values)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * y for i, y in zip(x, y_values))
        
        denom = (n * sum_xx - sum_x ** 2)
        if denom == 0: return 0, 0, 0, 0
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate Residuals for R2 and StdDev
        mean_y = sum_y / n
        ssr = 0 # Sum of Squared Residuals
        sst = 0 # Total Sum of Squares
        
        for i, y in enumerate(y_values):
            pred = slope * i + intercept
            ssr += (y - pred) ** 2
            sst += (y - mean_y) ** 2
            
        r2 = 1 - (ssr / sst) if sst > 0 else 0
        std_dev = math.sqrt(ssr / (n - 1)) if n > 1 else 0
        
        return slope, intercept, r2, std_dev

    def _execute_exit(self, symbol):
        if symbol in self.holdings:
            del self.holdings[symbol]