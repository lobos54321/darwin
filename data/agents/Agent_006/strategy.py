import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy Parameters
        self.history_maxlen = 60
        self.ema_fast_period = 12
        self.ema_slow_period = 26
        self.rsi_period = 14
        self.trade_amount_usd = 100.0
        
        # State
        self.history = {}  # {symbol: deque}
        self.banned_tags = set()

    def on_hive_signal(self, signal: dict):
        """Handle external signals."""
        if "penalize" in signal:
            for tag in signal["penalize"]:
                self.banned_tags.add(tag)

    def _calculate_ema(self, data, period):
        """Calculates the current Exponential Moving Average."""
        if len(data) < period:
            return None
        
        # Initial SMA
        ema = sum(list(data)[:period]) / period
        k = 2 / (period + 1)
        
        # Iterative EMA
        for price in list(data)[period:]:
            ema = (price - ema) * k + ema
            
        return ema

    def _calculate_rsi(self, data):
        """Calculates the Relative Strength Index."""
        if len(data) < self.rsi_period + 1:
            return 50.0

        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        
        # Use simple moving average for initial RSI calculation to avoid heavy iterative smoothing dependence
        recent_changes = changes[-self.rsi_period:]
        
        avg_gain = sum(x for x in recent_changes if x > 0) / self.rsi_period
        avg_loss = sum(abs(x) for x in recent_changes if x < 0) / self.rsi_period

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        """
        Analyzes all symbols and selects the single best Trend Following candidate.
        Eliminates RANDOM_TEST by ranking candidates.
        Eliminates DIP_BUY by requiring price > fast_ema > slow_ema.
        """
        candidates = []
        
        # 1. Update History & Identify Candidates
        # Sorted keys ensure deterministic processing order before ranking
        for symbol in sorted(prices.keys()):
            current_price = prices[symbol]["priceUsd"]
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_maxlen)
            self.history[symbol].append(current_price)
            
            # Need enough data for Slow EMA
            if len(self.history[symbol]) < self.ema_slow_period:
                continue

            price_series = list(self.history[symbol])
            
            # Calculate Indicators
            ema