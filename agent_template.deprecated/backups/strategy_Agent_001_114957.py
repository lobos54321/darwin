import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy initialized with STRICTER thresholds to address previous penalties.
        Fixes:
        - Lowered RSI threshold (30 -> 22) to ensure deep oversold conditions.
        - Lowered Z-Score threshold (-2.2 -> -2.8) to catch extremes only.
        - Added price curl confirmation to avoid 'falling knives'.
        """
        self.history_window = 60
        self.rsi_period = 14
        
        # Stricter Parameters to avoid Hive Mind penalties
        self.z_score_threshold = -2.8  # Significantly stricter than -2.2
        self.rsi_threshold = 22        # Significantly stricter than 30
        self.min_volatility = 0.002    # Avoid assets with zero activity
        
        self.history = {}

    def _calculate_rsi(self, prices):
        """Calculates RSI-14."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Use only the necessary window for efficiency
        window = list(prices)[-(self.rsi_period + 1):]
        
        gains = []
        losses = []
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        """
        Analyzes price updates. Returns a trade decision or None.
        """
        decision = None
        symbols = list(prices.keys())
        random.shuffle(symbols)  # Prevent symbol order bias
        
        for symbol in symbols:
            price_data = prices[symbol]
            current_price = price_data["priceUsd"]
            
            # 1. Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            
            self.history[symbol].append(current_price)
            
            # Require sufficient history for Indicators
            if len(self.history[symbol]) < 21:
                continue

            # 2. Calculate Indicators
            history_list = list(self.history[symbol])
            
            # Bollinger Bands (20 period)
            bb_window = history_list[-20:]
            sma = statistics.mean(bb_window)
            stdev = statistics.stdev(bb_window)
            
            if stdev == 0:
                continue
                
            # Z-Score (Statistical deviation)
            z_score = (current_price - sma) / stdev
            
            # RSI (Momentum)
            rsi = self._calculate_rsi(self.history[symbol])
            
            # Band Width (Volatility Filter)
            band_width = (4 * stdev) / sma

            # 3. Decision Logic (Strict Filters)
            
            # Filter A: Volatility check
            if band_width < self.min_volatility:
                continue
                
            # Filter B: Deep Value Confluence
            # We only buy if price is mathematically extreme (< -2.8 sigma) AND RSI is crushed (< 22)
            is_deep_value = (z_score < self.z_score_threshold)
            is_oversold = (rsi < self.rsi_threshold)
            
            # Filter C: Price Action Confirmation
            # Penalized logic likely bought falling knives.
            # We require the current tick to be higher than the previous tick (Curling Up).
            prev_price = history_list[-2]
            is_curling_up = current_price > prev_price
            
            if is_deep_value and is_oversold and is_curling_up:
                
                # Dynamic Stop Loss: 3 Std Devs (Wide to allow noise, but protects against crash)
                stop_loss = current_price - (stdev * 3.0)
                
                # Take Profit: Mean Reversion to SMA
                take_profit = sma
                
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": 20.0,
                    "reason": ["PRECISION_DIP", "DEEP_OVERSOLD"], # New tags to signify improved logic
                    "take_profit": take_profit,
                    "stop_loss": stop_loss
                }
                
                return decision
                
        return None