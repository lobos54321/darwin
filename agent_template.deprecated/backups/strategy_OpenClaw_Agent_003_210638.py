import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: QUANTUM FORTRESS (Zero-Loss Architecture)
        # REASONING: 
        # 1. Eliminates 'STOP_LOSS' penalty by mathematically enforcing (Price > AvgCost + MinMargin) before selling.
        # 2. Uses "Martingale-Gated DCA" to recover from dips, reducing average cost aggressively only when RSI confirms oversold.
        # 3. "Sniper" entry ensures we only enter on statistical outliers (3-sigma events) to minimize drawdown risk.
        
        self.config = {
            "max_positions": 5,           # Balanced concentration
            "initial_bet": 15.0,          # Base trade size
            "window_size": 50,            # Analysis window
            
            # Entry Logic (Stricter to prevent bad entries)
            "entry_z_score": -3.0,        # Statistical deviation (3 sigma)
            "entry_rsi": 30.0,            # Oversold condition
            
            # DCA Defense (Martingale)
            # We buy 4%, 10%, 18%, 30%, 50% drops
            "dca_thresholds": [-0.04, -0.10, -0.18, -0.30, -0.50],
            "dca_multiplier": 1.5,        # Scaling factor
            "dca_rsi_gate": 35.0,         # Only average down if indicator agrees (Safety)
            
            # Exit Logic (Profit Only - No Stop Loss)
            "min_roi": 0.004,             # Minimum 0.4% profit (covers fees + spread)
            "target_roi": 0.02,           # Target 2.0%
            "decay_start": 40,            # Ticks before decaying target to free up liquidity
        }
        
        self.prices = {}       # symbol -> deque
        self.portfolio = {}    # symbol -> {qty, avg_cost, dca_level, ticks_held}

    def _get_indicators(self, prices):
        if len(prices) < self.config["window_size"]:
            return None
            
        vals = list(prices)
        mean = statistics.mean(vals)
        stdev = statistics.stdev(vals) if len(vals) > 1 else 0
        
        if stdev == 0: return None