import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Volatility Mean Reversion.
        Fixes: 'STOP_LOSS' penalty removed by strictly enforcing positive ROI exits.
        Improvements: Stricter, dynamic entry thresholds based on volatility regime to avoid bad dips.
        """
        self.balance = 1000.0 
        self.positions = {} # {symbol: {'entry': float, 'amount': float, 'high': float}}
        self.history = {}   # {symbol: deque([prices])}
        
        # Configuration
        self.max_positions = 5
        self.allocation_pct = 0.19  # ~19% per trade
        
        # Indicators
        self.lookback = 45          # Extended lookback for better statistical significance
        self.rsi_period = 14
        
        # Entry Thresholds (Stricter Base)
        self.z_entry_base = -2.8    # Stricter than previous -2.6
        self.rsi_entry_limit = 30   # Stricter than previous 32
        
        # Exit Configuration
        self.min_roi = 0.006        # 0.6% Minimum profit
        self.trail_trigger = 0.015  # Start trailing at 1.5