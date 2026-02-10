import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Hyper-Resilient Grid Strategy v3.1
        
        PENALTY FIXES:
        1. STOP_LOSS (Liquidation Protection): 
           - Implemented 'Deep Grid' architecture extending coverage to -60% drops.
           - Added Liquidity Reserve (20% balance hard-locked) to prevent total equity exhaustion.
           - Reduced concurrency (max_slots) to prevent correlation cascades.
        2. ENTRY_QUALITY:
           - Stricter Z-score (-3.0) and RSI (<28) confluence required to avoid falling knives.
        """
        self.balance = 1000.0
        self.initial_balance = 1000.0 # Track for safety checks
        
        # --- Solvency Grid ---
        # Mathematical spacing to survive nuclear market events (-60% drops).
        # Multipliers ensure average price drops faster than market price.
        self.grid_levels = [
            {'drop': 0.030, 'mult': 1.0},   # -3%
            {'drop': 0.080, 'mult': 1.5},   # -8%
            {'drop': 0.150, 'mult': 2.5},   # -15%
            {'drop': 0.300, 'mult': 4.0},   # -30%
            {'drop': 0.600, 'mult': 6.0},   # -60% (Survival mode)
        ]
        
        # --- Risk Management ---
        # Calculate max exposure to ensure we never run out of funds for the final DCA.
        # Total multiplier per slot = 1 (base) + 1 + 1.5 + 2.5 + 4 + 6 = 16x
        total_mult = 1.0 + sum(lvl['mult'] for lvl in self.grid_levels)
        
        self.max_slots = 3             # Limit exposure to 3 concurrent assets
        self.reserve_ratio = 0.20      # Keep 20% cash untouchable for stability
        
        # Dynamic Base Order Calculation
        # Formula: (Balance * (1 - Reserve)) / (Slots * Max_Multiplier_Per_Slot)
        # Prevents over-leveraging even if all slots hit max drawdown.
        allocatable_balance = self.balance * (1.0 - self.reserve_ratio)
        self.base_order = allocatable_balance / (self.max_slots * total_mult)
        
        # --- Entry Parameters ---
        self.lookback = 50
        self.entry_z = -3.00     # Strict deviation check
        self.entry_rsi = 28.0    # Deep oversold confirmation
        self.min_vol = 0.0005    # Minimum volatility threshold
        
        self.positions = {} 
        self.history = {}
        self.cooldown