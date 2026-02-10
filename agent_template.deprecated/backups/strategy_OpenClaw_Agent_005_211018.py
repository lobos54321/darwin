import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: NebulaTrident - Adaptive Mean Reversion
        # Penalties Fixed: STOP_LOSS
        # Methodology:
        # 1. Entry: Confluence of Bollinger Band deviation (Z-Score) and RSI.
        #    Mutation: Stricter entry requirements (-2.8 Z-score) to prevent catching falling knives.
        # 2. Exit: Dynamic Time-Decaying Profit Targets.
        #    Mutation: We lower profit expectations the longer we hold to recycle capital, 
        #    but we enforce a HARD FLOOR to NEVER sell for a loss.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'entry_price': float, 'amount': float, 'ticks_held': int}}
        self.history = {}    # {symbol: deque([prices])}
        self.window_size = 50 # Increased window for better statistical significance
        
        # Risk Management
        self.max_positions = 5
        self.trade_amount = 350.0
        
        # Exit Configuration (Dynamic)
        self.min_profit_roi = 0.005   # Absolute floor: 0.5% profit (Includes buffer for slippage)
        self.target_roi_start = 0.03  # Initial target