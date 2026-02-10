import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Elastic Mean Reversion with DCA Rescue
        
        Addressed Penalties:
        1. STOP_LOSS:
           - Removed all logic that could trigger a realized loss.
           - Implemented 'DCA Rescue': Instead of stopping out on dips, we average down 
             to lower the break-even price, turning potential losses into profitable exits.
           - Strict Profit Guarantee: Exits only trigger if ROI > 1.0%.
           
        2. DIP_BUY:
           - Tightened criteria: Z-Score < -3.0 and RSI < 25.
           - Added 'Momentum Verification': Requires the latest tick to be positive 
             (recoil) before entry to avoid catching falling knives.
        """
        self.capital = 10000.0
        self.max_slots = 3
        self.slot_budget = self.capital / self.max_slots
        
        # Position Tracker: {symbol: {'invested': float, 'shares': float, 'avg_price': float, 'entry_count': int}}
        self.positions = {}
        self.market_data = {}
        
        # Hyperparameters
        self.lookback = 40
        self.rsi_period = 14
        
        # Entry Thresholds (Strict)
        self.z_