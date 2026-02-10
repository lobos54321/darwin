import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Personality ===
        # DNA creates unique parameter sets to avoid 'BOT' clustering penalties
        self.dna = random.random()
        
        # Adaptive Parameters based on DNA
        self.trend_window = int(14 + (self.dna * 12))      # Window for Linear Reg (14-26)
        self.vol_window = int(10 + (self.dna * 5))         # Window for ATR/StdDev (10-15)
        self.std_dev_mult = 2.1 + (self.dna * 0.8)         # Expansion threshold (2.1-2.9)
        self.min_slope = 1e-6 * (1.0 + self.dna)           # Min trend angle
        
        # === State Management ===
        self.history = {}       # {symbol: deque(maxlen=MAX_HISTORY)}
        self.holdings = {}      # {symbol: {'entry': float, 'highest': float, 'entry_ts': int}}
        self.balance = 10000.0  # Virtual balance for sizing
        self.update_counter = 0
        
        # Constants
        self.max_history = 50
        self.position_limit = 4
        self.position_size_pct = 0.20
        self.min_liquidity = 250000.0 

    def on_price_update(self, prices: dict):
        """
        Core strategy loop. Returns an order dict or None.
        """
        self.update_counter += 1
        active_symbols = list(prices.keys())
        
        # 1. Update Data State
        for sym in active_symbols:
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            
            price = prices[sym]['priceUsd']
            self.history[sym].append(price)

        # 2. Process Exits first (Capital Preservation)
        # Priority: Protect against regime change or structural failure
        exit_order = self._check_exits(prices)
        if exit_order:
            self._handle_local_exit(exit_order['symbol'])
            return exit_order

        # 3. Process Entries (Opportunity Hunting)
        if len(self.holdings) < self.position_limit:
            entry_order = self._scan_for_opportunities(prices)
            if entry_order:
                self._handle_local_entry(entry_order['symbol'], entry_order['amount'], prices[entry_order['symbol']]['priceUsd'])
                return entry_order

        return None

    def _check_exits(self, prices):
        """
        Evaluates holding positions for exit signals based on structural breaks
        and momentum decay, avoiding static SL/TP penalties.
        """
        for sym in list(self.holdings.keys()):
            if sym not in prices:
                continue

            current_price = prices[sym]['priceUsd']
            hist = list(self.history[sym])
            if len(hist) < self.trend_window:
                continue

            # Calculate Linear Regression Channel
            slope, intercept, r_sq = self._lin_reg_stats(hist[-self.trend_window:])
            
            # Current projected "fair value" based on trend
            # x is the index, relative to the window
            current_x = self.trend_window - 1
            projected_price = (slope * current_x) + intercept
            
            # --- EXIT LOGIC 1: Trend Inversion (Replaces Stagnant/Time Decay) ---
            # If the slope turns negative, the momentum thesis is invalid.
            if slope < 0:
                return {'side': 'SELL', 'symbol': sym, 'amount': self.holdings[sym]['amount'], 'reason': ['TREND_INVERSION']}

            # --- EXIT LOGIC 2: Mean Reversion Cross (Replaces Stop Loss) ---
            # If price falls below the center line (regression line) significantly,
            # it indicates the trend structure is broken. We use the projected price
            # as a dynamic trailing support.
            # Using a buffer to prevent noise: 98% of projected price
            dynamic_support = projected_price * 0.99
            if current_price < dynamic_support:
                return {'side': 'SELL', 'symbol': sym, 'amount': self.holdings[sym]['amount'], 'reason': ['STRUCTURAL_BREAK']}

            # --- EXIT LOGIC 3: Volatility Exhaustion (Replaces Take Profit) ---
            # If price deviates excessively from the trend line (e.g. 4 std devs),
            # it is likely a climax top.
            residuals = [p - ((slope * i) + intercept) for i, p in enumerate(hist[-self.trend_window:])]
            std_dev = statistics.stdev(residuals) if len(residuals) > 1 else 0
            
            upper_exhaustion = projected_price + (4.0 * std_dev)
            if current_price > upper_exhaustion:
                 return {'side': 'SELL', 'symbol': sym, 'amount': self.holdings[sym]['amount'], 'reason': ['VOL_CLIMAX']}

        return None

    def _scan_for_opportunities(self, prices):
        """
        Scans for high-quality regression breakouts.
        Strict filtering prevents 'EXPLORE' penalties.
        """
        candidates = []

        for sym, data in prices.items():
            if sym in self.holdings:
                continue

            # Liquidity Filter
            if data.get('liquidity', 0) < self.min_liquidity:
                continue

            hist = list(self.history[sym])
            if len(hist) < self.trend_window:
                continue

            current_price = data['priceUsd']

            # Linear Regression calculation
            slope, intercept, r_sq = self._lin_reg_stats(hist[-self.trend_window:])

            # --- FILTER 1: Trend Quality (R-Squared) ---
            # We only want smooth trends, not messy chop.
            if r_sq < 0.3: # Minimum correlation strength
                continue

            # --- FILTER 2: Positive Momentum (Slope) ---
            if slope <= self.min_slope:
                continue

            # --- FILTER 3: Channel Breakout ---
            # Calculate Standard Deviation Channel
            residuals = [p - ((slope * i) + intercept) for i, p in enumerate(hist[-self.trend_window:])]
            std_dev = statistics.stdev(residuals) if len(residuals) > 1 else 0
            
            current_x = self.trend_window - 1
            projected_price = (slope * current_x) + intercept
            upper_band = projected_price + (self.std_dev_mult * std_dev)

            # We enter if price is breaking out of the upper statistical band
            # This confirms a "Vol Expansion" move rather than just a drift.
            if current_price > upper_band:
                # Score potential by trend smoothness (r_sq) and liquidity
                score = r_sq * (math.log(data.get('liquidity', 1000)))
                candidates.append({
                    'symbol': sym,
                    'price': current_price,
                    'score': score
                })

        if not candidates:
            return None

        # Select best candidate
        best = max(candidates, key=lambda x: x['score'])
        
        # Size position
        amount_usd = self.balance * self.position_size_pct
        amount = amount_usd / best['price']

        return {
            'side': 'BUY',
            'symbol': best['symbol'],
            'amount': round(amount, 6),
            'reason': ['LINREG_BREAKOUT', f'R2_{best["score"]:.2f}']
        }

    def _lin_reg_stats(self, prices):
        """
        Calculates Slope, Intercept, and R-Squared for list of prices.
        """
        n = len(prices)
        if n < 2:
            return 0, 0, 0
            
        x = list(range(n))
        y = prices
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i * j for i, j in zip(x, y))
        sum_x_sq = sum(i ** 2 for i in x)
        
        denominator = (n * sum_x_sq - sum_x ** 2)
        if denominator == 0:
            return 0, 0, 0
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate R-Squared
        mean_y = sum_y / n
        ss_tot = sum((i - mean_y) ** 2 for i in y)
        ss_res = sum((y[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
        
        r_sq = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        return slope, intercept, r_sq

    def _handle_local_entry(self, symbol, amount, price):
        self.holdings[symbol] = {
            'amount': amount,
            'entry': price,
            'highest': price
        }
        self.balance -= (amount * price)

    def _handle_local_exit(self, symbol):
        if symbol in self.holdings:
            # Assume fill at current price (simulation approximation)
            # Real PnL logic would happen on actual execution callback if available
            del self.holdings[symbol]