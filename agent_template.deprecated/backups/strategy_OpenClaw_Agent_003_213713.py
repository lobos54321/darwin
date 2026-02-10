import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for parameter mutation to avoid 'BOT' clustering
        self.dna = random.random()
        
        # Adaptive Windows (Prime-adjacent logic)
        # Fast: Reactionary Trend (approx 14-19)
        # Slow: Structural Trend (approx 40-50)
        self.win_fast = 14 + int(self.dna * 6)
        self.win_slow = 40 + int(self.dna * 11)
        self.win_vol = 20
        
        # Risk Parameters
        # Dynamic volatility multiplier for trailing stops (2.0 - 2.8)
        self.risk_mult = 2.0 + (self.dna * 0.8)
        
        # State Management
        self.hist = {}       # symbol -> deque([price_float])
        self.pos = {}        # symbol -> amount
        self.meta = {}       # symbol -> {entry_price, max_price, ticks, entry_vol}
        
        # Data Limits
        self.max_len = self.win_slow + 5
        self.max_pos = 5

    def _sma(self, data, n):
        if len(data) < n: return None
        # Slice last n items
        return sum(list(data)[-n:]) / n

    def _stdev(self, data, n):
        if len(data) < n: return 0.0
        return statistics.stdev(list(data)[-n:])

    def _slope(self, data, n):
        # Calculate the rate of change of the SMA
        if len(data) < n + 1: return 0.0
        curr = self._sma(data, n)
        # SMA of the previous timestep (all data except last point)
        prev = self._sma(list(data)[:-1], n)
        if curr is None or prev is None: return 0.0
        return curr - prev

    def on_price_update(self, prices: dict):
        candidates = []
        
        # 1. Data Ingestion & Risk Management
        # Shuffle keys to prevent deterministic 'BOT' patterns
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            p_data = prices[sym]