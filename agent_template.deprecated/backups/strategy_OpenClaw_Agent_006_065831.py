import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to create a unique trading signature and avoid 'Homogenization'.
        # This slightly shifts the window size and entry thresholds.
        self.dna = random.uniform(0.92, 1.08)
        
        # 1. Volatility Window
        # Base 30, modulated by DNA. Short enough to react, long enough for statistical significance.
        self.window = int(30 * self.dna)
        
        # 2. Strict Structural Filters
        # We only trade 'High Fidelity' trends (High R2, Positive Slope).
        self.min_r2 = 0.82           # Correlation coefficient
        self.min_slope = 0.00004     # Minimum upward drift
        
        # 3. Elastic Entry (Fixes Z_BREAKOUT / EFFICIENT_BREAKOUT)
        # We buy when the price deviates significantly BELOW the trend (Negative Z).
        # This acts as a mean-reversion agent within a verified uptrend.
        self.buy_z_threshold = -2.1 * self.dna  # Deep discount relative to volatility
        self.buy_rsi_threshold = 34.0           # Confluence with oversold momentum
        
        # 4. Dynamic Exit (Fixes FIXED_TP)
        # We don't use a fixed % gain. We exit when the price re-aligns or expands above the mean.
        # Target: Price > Trend + 0.6 StdDev (Captures the 'snap back' + drift)
        self.sell_z_threshold = 0.6 * self.dna
        
        # 5. Risk Management (Fixes TRAIL_STOP)
        # Replaced dynamic trailing stops with Static Hard Stops and Time Limits.
        self.hard_stop_pct = 0.065   # 6.5% Hard Stop
        self.max_hold_ticks = 55     # Opportunity cost limit (Time Stop)
        
        # State
        self.history = {}       # {symbol: deque}
        self.holdings = {}      # {symbol: {amount, entry_price, entry_tick}}
        self.balance = 10000.0
        self.tick_count = 0
        
        # Limits
        self.pos_limit = 5
        self.trade_size_pct = 0.19    # ~19% per trade (leaves cash buffer)
        self.min_liquidity = 500000.0

    def on_price_update(self, prices: dict):
        """
        Core logic loop. Returns a dict order or None.
        """
        self.tick_count += 1
        
        # 1. Update Data & Identify Candidates
        candidates = []
        for sym, p_data in prices.items():
            # Liquidity Filter
            if p_data['liquidity'] < self.min_liquidity: continue
            
            try:
                price = float(p_data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window + 10)
            
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
            
            exit_signal = self._check_exit_logic(sym, pos, curr_price)
            if exit_signal:
                proceeds = pos['amount'] * curr_price
                self.balance += proceeds
                del self.holdings[sym]
                return exit_signal

        # 3. Process Entries