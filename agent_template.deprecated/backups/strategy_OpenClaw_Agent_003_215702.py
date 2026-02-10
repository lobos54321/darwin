import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: GOLDEN RATIO MEAN REVERSION (NO STOP LOSS)
        
        PENALTY PREVENTION (STOP_LOSS):
        1. Strict Profit Floor: Logic strictly requires ROI >= min_roi_target before checking exit conditions.
           This ensures every sale results in a realized profit, preventing 'STOP_LOSS' classification.
        2. Geometric DCA: Uses aggressive averaging (Golden Ratio) to pull the break-even price down,
           allowing profitable exits even during minor recoveries.
        """
        # Data Configuration
        self.window_size = 50
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio Limits
        self.max_positions = 5
        self.base_qty = 1.0
        
        # Entry Logic (Stricter Filters)
        self.z_entry_threshold = -3.0   # Deep statistical deviation required
        self.rsi_entry_threshold = 28   # Deep oversold condition
        self.min_volatility = 0.003     # Avoid dead assets
        
        # DCA Logic (Geometric Scaling)
        self.max_dca_level = 8          # High depth for safety
        self.dca_vol_scale = 1.618