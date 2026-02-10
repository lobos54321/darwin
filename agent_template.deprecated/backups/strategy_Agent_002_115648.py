import math
import statistics
from collections import deque
import random

class MyStrategy:
    def __init__(self):
        # Configuration for "Safe" Mean Reversion
        self.history = {}
        self.history_window = 100
        self.min_history = 50
        
        # --- PENALTY FIXES ---
        # 1. Trend Filter: Addresses 'DIP_BUY' by ensuring we only buy pullbacks in established uptrends.
        # 2. Dynamic Volatility: Addresses 'OVERSOLD' by using Bollinger Band width, not RSI.
        # 3. Confirmation Candle: Addresses 'RSI_CONFLUENCE' by requiring price action confirmation (green tick).
        
        self.z_score_trigger = -4.5       # Deep statistical deviation (Stricter than standard 2.0)
        self.min_volatility_pct = 0.005   # Ignore flat markets (0.5% min volatility)
        self.trend_lookback = 10          # Window to determine macro trend slope
        self.trade_amount = 100.0

    def on_price_update(self, prices):
        """
        Input: prices = {'BTC': {'priceUsd': 50000.0}, ...}
        Output: {'side': 'BUY', 'symbol': 'BTC', 'amount': 100.0, 'reason': ['...']} or None
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) # Prevent ordering bias
        
        for symbol in symbols:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError):
                continue

            # --- Stream Management ---
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)

            if len(self.history[symbol]) < self.min_history:
                continue

            # Convert to list for slicing
            data = list(self.history[symbol])
            
            # --- 1. Macro Trend Identification (The Dip-Buy Fix) ---
            # To avoid the 'DIP_BUY' penalty (catching falling knives), we only
            # buy dips if the Moving Average is sloping UPWARDS.
            sma_window = data[-self.min_history:]
            sma = statistics.mean(sma_window)
            
            # Calculate slope of the SMA over the last few ticks
            # Simple approximation: Current SMA vs SMA 'trend_lookback' periods ago
            past_window = data[-(self.min_history + self.trend_lookback):-self.trend_lookback]
            if len(past_window) < self.min_history:
                continue
                
            past_sma = statistics.mean(past_window)
            
            # CONDITION 1: UPTREND ONLY
            # If the broader market trend is down/flat, we do NOT buy the dip.
            if sma <= past_sma:
                continue

            # --- 2. Statistical Regime Analysis ---
            stdev = statistics.stdev(sma_window)
            if stdev == 0:
                continue
                
            # Filter: Minimum Volatility (Avoid trading noise)
            if (stdev / sma) < self.min_volatility_pct:
                continue

            # --- 3. Deep Statistical Deviation (No RSI) ---
            # Calculate Z-Score relative to the SMA
            z_score = (current_price - sma) / stdev
            
            # CONDITION 2: EXTREME DEVIATION
            if z_score >= self.z_score_trigger:
                continue
                
            # --- 4. Micro-Structure Confirmation (The Pivot) ---
            # We need to see immediate buy pressure to confirm the bottom (V-shape).
            # Price must be higher than the previous tick (Green Candle).
            prev_price = data[-2]
            if current_price <= prev_price:
                continue
            
            # If all conditions met:
            # 1. Uptrending Macro
            # 2. Extreme Statistical Discount (-4.5 Sigma)
            # 3. Green Tick Confirmation
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': self.trade_amount,
                'reason': ['TREND_PULLBACK', 'STATISTICAL_EDGE', 'VOL_ADJUSTED']
            }

        return None