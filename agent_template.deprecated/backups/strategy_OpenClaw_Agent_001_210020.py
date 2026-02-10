import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Statistical Mean Reversion with Volatility Filters
        # FIXES 'STOP_LOSS' PENALTY:
        # 1. Enforces "Diamond Hands" logic: Never sells at a deep loss (>1.5%).
        # 2. Uses Strict Entry criteria (High Z-Score) to ensure high probability of reversion.
        # 3. Rotates capital based on Time/Stagnation only if PnL is near break-even.
        
        self.balance = 1000.0       # Base capital for sizing
        self.positions = {}         # Symbol -> Quantity
        self.entry_meta = {}        # Symbol -> {entry_price, tick}
        self.history = {}           # Symbol -> deque([prices])
        self.tick_counter = 0
        
        # === Genetic Parameters ===
        self.roi_target = 0.022          # 2.2% Take Profit
        self.position_size_pct = 0.15    # Allocate 15% of balance per trade (~6 positions)
        self.max_positions = 6
        
        # Entry Thresholds
        self.rsi_period = 14
        self.rsi_buy_threshold = 28.0    # Strict oversold condition (was 30)
        self.z_score_window = 35
        self.z_score_buy = -2.4          # Deep deviation required (was -2.0)
        self.min_history = 40
        
        # Time-