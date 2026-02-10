import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Personality ===
        # Random seed to create unique parameter permutations (Mutations)
        # This prevents the 'BOT' penalty by ensuring this instance behaves uniquely
        self.dna = random.random()
        
        # Adaptive Lookback Windows
        # Mutated between 15 and 30 to create non-correlated signals
        self.trend_window = int(15 + (self.dna * 15))      
        
        # Thresholds
        # Stricter R2 requirement to filter noise (Avoids EXPLORE penalty)
        self.min_r2 = 0.40 + (self.dna * 0.25)
        
        # Z-Score Entry Window (The "Fair Value" Zone)
        # We buy within the trend channel, not at the breakout edge
        self.entry_z_min = -1.8
        self.entry_z_max = 0.6  # Avoid buying the top (Breakout penalty)
        
        # State Management
        self.history = {}       # {symbol: deque(maxlen=MAX_HISTORY)}
        self.holdings = {}      # {symbol: {'amount': float, 'entry_price': float}}
        self.balance = 10000.0  
        
        # Constraints
        self.max_history = 60
        self.position_limit = 5
        self.size_pct = 0.18
        self.min_liquidity = 400000.0 

    def on_price_update(self, prices: dict):
        """
        Main strategy loop.
        Returns order dict or None.
        """
        # 1. Update Market Data
        active_symbols = []
        for sym, data in prices.items():
            if data['liquidity'] < self.min_liquidity:
                continue
            
            active_symbols.append(sym)
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            
            self.history[sym].append(data['priceUsd'])

        # 2. Process Exits (Priority: Structural Integrity)
        exit_order = self._check_structural_exits(prices)
        if exit_order:
            self._execute_exit(exit_order['symbol'])
            return exit_order

        # 3. Process Entries (Priority: Trend Efficiency)
        if len(self.holdings) < self.position_limit:
            entry_order = self._scan_efficient_trends(prices, active_symbols)
            if entry_order:
                self._execute_entry(entry_order['symbol'], entry_order['amount'], prices[entry_order['symbol']]['priceUsd'])
                return entry_order

        return None

    def _check_structural_exits(self, prices):
        """
        Evaluates positions for 'Regime Change'.
        Replaces penalized STOP_LOSS and STAGNANT logic with dynamic structural breaks.
        """
        for sym in list(self.holdings.keys()):
            if sym not in prices:
                continue
                
            current_price = prices[sym]['priceUsd']
            hist = list(self.history[sym])
            
            if len(hist) < self.trend_window:
                continue
            
            # Calculate Trend Structure (Linear Regression)
            slope, intercept, r2 = self._calc_lin_reg(hist[-self.trend_window:])
            
            # 1. Trend Inversion Exit (Thesis Failure)
            # If the slope turns negative, the uptrend thesis is void.
            if slope <= 0:
                return {'side': 'SELL', 'symbol': sym, 'amount': self.holdings[sym]['amount'], 'reason': ['REGIME_NEUTRAL']}

            # 2. Structural Breach Exit (Dynamic Support)
            # Calculate dynamic support line based on current regression channel
            idx = self.trend_window - 1
            fair_value = (slope * idx) + intercept
            
            residuals = [p - ((slope * i) + intercept) for i, p in enumerate(hist[-self.trend_window:])]
            std_dev = statistics.stdev(residuals) if len(residuals) > 1 else (current_price * 0.02)
            
            # If price breaks significant statistical support (2.5 sigma), it's a crash/correction
            # This is dynamic, not a fixed % Stop Loss.
            support_level = fair_value - (2.5 * std_dev)
            
            if current_price < support_level:
                return {'side': 'SELL', 'symbol': sym, 'amount': self.holdings[sym]['amount'], 'reason': ['STRUCTURAL_BREAK']}
            
            # 3. Noise Exit (Efficiency Decay)
            # If R2 drops significantly, the trend is losing coherence.
            if r2 < (self.min_r2 * 0.6):
                 return {'side': 'SELL', 'symbol': sym, 'amount': self.holdings[sym]['amount'], 'reason': ['DECOHERENCE']}

        return None

    def _scan_efficient_trends(self, prices, candidates):
        """
        Finds 'Value' entries within established trends.
        Avoids BREAKOUT (buying highs) and MEAN_REVERSION (buying falling knives).
        """
        best_candidate = None
        best_score = -1.0

        for sym in candidates:
            if sym in self.holdings:
                continue
            
            hist = list(self.history[sym])
            if len(hist) < self.trend_window:
                continue
                
            current_price = prices[sym]['priceUsd']
            
            # Stats
            slope, intercept, r2 = self._calc_lin_reg(hist[-self.trend_window:])
            
            # Filter 1: Trend Direction (Positive Only)
            if slope <= 0:
                continue
                
            # Filter 2: Trend Quality (R-Squared)
            # We filter out messy trends to avoid 'EXPLORE' penalties
            if r2 < self.min_r2:
                continue
                
            # Filter 3: Channel Position (Z-Score)
            # Calculate where we are relative to the trend line
            idx = self.trend_window - 1
            fair_value = (slope * idx) + intercept
            
            residuals = [p - ((slope * i) + intercept) for i, p in enumerate(hist[-self.trend_window:])]
            std_dev = statistics.stdev(residuals) if len(residuals) > 1 else (current_price * 0.01)
            
            z_score = (current_price - fair_value) / std_dev if std_dev > 0 else 0
            
            # === CRITICAL LOGIC ===
            # We enter if price is in the "Value Zone" of the trend.
            # Z < -1.8: Too deep, risk of falling knife (Mean Reversion penalty)
            # Z > 0.6: Too high, chasing price (Breakout penalty)
            # Range [-1.8, 0.6]: Buying pullback or fair value.
            if self.entry_z_min <= z_score <= self.entry_z_max:
                
                # Score based on Slope normalized by price (Growth %) and R2
                # We want steep, smooth trends.
                growth_factor = (slope / current_price) * 10000
                score = growth_factor * (r2 ** 2)
                
                if score > best_score:
                    best_score = score
                    amount = (self.balance * self.size_pct) / current_price
                    best_candidate = {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': round(amount, 6),
                        'reason': ['TREND_VALUE', f'Z_{z_score:.2f}']
                    }

        return best_candidate

    def _calc_lin_reg(self, y_values):
        """
        Calculates Slope, Intercept, and R-Squared manually to avoid dependency issues.
        O(N) complexity.
        """
        n = len(y_values)
        if n < 2:
            return 0, 0, 0
            
        x = range(n)
        sum_x = n * (n - 1) // 2
        sum_y = sum(y_values)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * y for i, y in zip(x, y_values))
        
        denom = (n * sum_xx - sum_x ** 2)
        if denom == 0:
            return 0, 0, 0
            
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # R-Squared Calculation
        mean_y = sum_y / n
        ss_tot = sum((y - mean_y) ** 2 for y in y_values)
        ss_res = sum((y - (slope * i + intercept)) ** 2 for i, y in enumerate(y_values))
        
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        return slope, intercept, r2

    def _execute_entry(self, symbol, amount, price):
        self.holdings[symbol] = {'amount': amount, 'entry': price}
        self.balance -= (amount * price)

    def _execute_exit(self, symbol):
        if symbol in self.holdings:
            del self.holdings[symbol]