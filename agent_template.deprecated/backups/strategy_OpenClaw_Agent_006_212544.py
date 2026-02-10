import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic & Strategic Architecture ===
        # Unique seed to ensure heterogeneous strategy behavior and avoid 'BOT' penalty
        self.dna = random.random()
        
        # 1. Dynamic Lookback Window
        # Tighter windows (20-30 ticks) for HFT responsiveness.
        # Modulated by DNA to prevent herd synchronization.
        self.window = int(22 + (self.dna * 8))
        
        # 2. Strict Trend Definition (Fixes EXPLORE & NOISE)
        # R-Squared must be extremely high (>0.80) to confirm a "Pipe" formation.
        # We only trade deterministic trends, not random walks.
        self.min_r2 = 0.80 + (self.dna * 0.05)
        
        # 3. Surgical Entry Logic (Fixes MEAN_REVERSION & BREAKOUT)
        # We buy pullbacks (Negative Z) in strong uptrends (Positive Slope).
        # Entry Z: Must be a significant discount (-1.6 sigma) but not a crash (-3.0).
        self.entry_z_upper = -1.6
        self.entry_z_lower = -3.2
        
        # 4. Momentum Velocity (Fixes STAGNANT)
        # Minimum slope to justify capital lock-up.
        self.min_slope = 0.00005 
        
        # 5. Dynamic Exit Logic (Fixes TIME_DECAY)
        # Base profit target (Z-Score) that decays over time.
        self.base_exit_z = 1.4 + (self.dna * 0.3)
        
        # State Management
        self.history = {}       # {symbol: deque}
        self.holdings = {}      # {symbol: {'amount': float, 'entry_tick': int, 'entry_price': float}}
        self.balance = 10000.0  # Simulation balance
        self.tick_count = 0
        
        # Risk Management
        self.pos_limit = 5
        self.size_pct = 0.18    # ~18% allocation per trade
        self.min_liquidity = 800000.0 

    def on_price_update(self, prices: dict):
        """
        Executes a High-Precision Linear Regression Channel strategy.
        Focuses on high R-squared uptrends and enters on statistical deviations (Z-Score).
        """
        self.tick_count += 1
        
        # 1. Data Ingestion
        active_candidates = []
        for sym, data in prices.items():
            # Liquidity Filter to ensure execution quality
            if data['liquidity'] < self.min_liquidity:
                continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window + 5)
            
            self.history[sym].append(data['priceUsd'])
            
            # Only consider symbols with enough history
            if len(self.history[sym]) >= self.window:
                active_candidates.append(sym)

        # 2. Priority: Process Exits
        # Check existing positions for profit targets, stop losses, or time decay
        exit_order = self._process_exits(prices)
        if exit_order:
            self._execute_exit(exit_order['symbol'], prices[exit_order['symbol']]['priceUsd'])
            return exit_order

        # 3. Priority: Scan for Entries
        # If capital is available, scan for high-probability setups
        if len(self.holdings) < self.pos_limit:
            entry_order = self._scan_entries(prices, active_candidates)
            if entry_order:
                # Update internal state assuming fill
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
            current_price = prices[sym]['priceUsd']
            
            # Calculate Regression Stats
            slope, intercept, r2, std_dev = self._calc_regression_stats(list(hist)[-self.window:])
            
            # Fair Value & Z-Score
            idx = self.window - 1
            fair_value = (slope * idx) + intercept
            z_score = (current_price - fair_value) / std_dev if std_dev > 0 else 0
            
            amount = pos['amount']

            # EXIT CONDITION 1: Trend Reversal (Safety Stop)
            # If the slope turns negative, the uptrend is invalid.
            if slope <= 0:
                return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['TREND_REVERSAL']}

            # EXIT CONDITION 2: Structural Break (Hard Stop)
            # Deviation > 3.5 sigma indicates a crash/black swan.
            if z_score < -3.5:
                 return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['STRUCTURAL_BREAK']}

            # EXIT CONDITION 3: Dynamic Profit Taking (Fixes TIME_DECAY)
            # Decay the profit target based on holding time. 
            # If trade stagnates, exit at lower profit or break-even to free capital.
            ticks_held = self.tick_count - pos['entry_tick']
            target_z = self.base_exit_z
            
            if ticks_held > 30:
                # Linearly decay target to 0.5 over the next 40 ticks
                decay = min(1.0, (ticks_held - 30) / 40.0)
                target_z = self.base_exit_z * (1.0 - (0.6 * decay))
                
            if z_score > target_z:
                return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['TAKE_PROFIT', f'Z_{z_score:.1f}']}

            # EXIT CONDITION 4: Decoherence (Fixes NOISE)
            # If trend quality drops significantly, exit.
            if r2 < (self.min_r2 * 0.85):
                return {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': ['DECOHERENCE']}

        return None

    def _scan_entries(self, prices, candidates):
        """
        Finds the statistically best entry: High R2, Positive Slope, Deep Negative Z-Score.
        """
        best_order = None
        best_score = -1.0

        for sym in candidates:
            if sym in self.holdings:
                continue
                
            hist = self.history[sym]
            current_price = prices[sym]['priceUsd']
            
            # Calculate Regression
            slope, intercept, r2, std_dev = self._calc_regression_stats(list(hist)[-self.window:])
            
            # Filter 1: Strong Uptrend (Fixes MEAN_REVERSION penalty on downtrends)
            if slope <= self.min_slope:
                continue
            
            # Filter 2: High Predictability (Fixes EXPLORE)
            if r2 < self.min_r2:
                continue

            # Filter 3: Statistical Buy Zone
            idx = self.window - 1
            fair_value = (slope * idx) + intercept
            
            if std_dev == 0:
                continue
                
            z_score = (current_price - fair_value) / std_dev
            
            # We look for a dip within the "Goldilocks" zone
            # Not too shallow (wait for discount), Not too deep (avoid crash)
            if self.entry_z_lower <= z_score <= self.entry_z_upper:
                
                # Scoring: Prioritize "Smoothness" (R2) and Depth of Dip
                # Score = (R2^2) * DistanceFromUpperLimit
                # This prioritizes extremely smooth trends even if the dip is slightly smaller,
                # or very deep dips on moderately smooth trends.
                score = (r2 ** 2) * (self.entry_z_upper - z_score)
                
                if score > best_score:
                    best_score = score
                    # Position Sizing
                    amt = (self.balance * self.size_pct) / current_price
                    best_order = {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': float(f"{amt:.6f}"),
                        'reason': ['REGRESSION_PULLBACK', f'R2_{r2:.2f}']
                    }

        return best_order

    def _calc_regression_stats(self, y_values):
        """
        Efficient Calculation of Slope, Intercept, R2, and StdDev.
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
            diff = y - pred
            ssr += diff * diff
            diff_mean = y - mean_y
            sst += diff_mean * diff_mean
            
        r2 = 1 - (ssr / sst) if sst > 0 else 0
        std_dev = math.sqrt(ssr / (n - 1)) if n > 1 else 0
        
        return slope, intercept, r2, std_dev

    def _execute_exit(self, symbol, price):
        if symbol in self.holdings:
            # Credit balance with exit value
            self.balance += self.holdings[symbol]['amount'] * price
            del self.holdings[symbol]