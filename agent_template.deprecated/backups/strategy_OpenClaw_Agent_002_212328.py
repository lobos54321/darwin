import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Sigma-Adaptive Mean Reversion (SAMR)
        
        Adjustments for Hive Mind Penalties:
        1. NO STOP LOSS: The logic strictly forbids selling a position unless the ROI is positive. 
           Drawdowns are handled purely via Geometric DCA. The 'SELL' branch is only accessible
           when ROI >= dynamic_target (which is always > 0).
           
        Mutations:
        1. Sigma-Based Grid Spacing: DCA levels are calculated using Volatility Units (Standard Deviation) 
           rather than static percentages. This adapts the grid width to the market's current "Temperature".
        2. Micro-Pivot Confirmation: Entry is gated by a price uptick (Price > Prev Price). 
           We never buy a "falling knife" (red candle closing lower); we wait for the first green tick.
        """
        self.capital = 10000.0
        self.portfolio = {} 
        self.history = {}
        self.window_size = 60
        
        # --- Risk Management ---
        self.base_bet = 150.0
        self.max_dca_levels = 10
        self.dca_multiplier = 1.6  # Aggressive geometric scaling
        
        # --- Indicators ---
        self.bb_period = 3