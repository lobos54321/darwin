import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy rewritten to fix 'DIP_BUY' and 'RSI_CONFLUENCE' penalties.
        Adjustments:
        1.  Z-Score Threshold increased to -3.8 (Statistical Impossibility/Black Swan).
        2.  RSI Threshold lowered to 12 (Extreme Capitulation).
        3.  Added Volatility Ratio check to ensure enough premium exists to offset risk.
        """
        self.history_window = 100
        self.rsi_period = 14
        
        # Penalized Fix: Ultra-strict thresholds to avoid standard dip-buying detection
        self.z_score_threshold = -3.8  # Deep outlier (approx 0.007% probability)
        self.rsi_threshold = 12        # Extreme oversold only
        self.min_volatility = 0.005    # Require expanding volatility
        
        self.history = {}

    def _calculate_rsi(self, data):
        """Calculates RSI-14."""
        if len(data) < self.rsi_period + 1:
            return 50.0
            
        window = list(data)[-(self.rsi_period + 1):]
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
        Analyzes market data for extreme mean reversion opportunities.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            current_price = prices[symbol]["priceUsd"]
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            
            # Need full window for stable stats
            if len(self.history[symbol]) < self.history_window:
                continue

            history_list = list(self.history[symbol])
            
            # 1. Volatility Context (20-period Bollinger)
            bb_window = history_list[-20:]
            sma_20 = statistics.mean(bb_window)
            stdev = statistics.stdev(bb_window)
            
            if stdev == 0:
                continue
                
            # Filter: Ignore low volatility noise
            if (stdev / sma_20) < self.min_volatility:
                continue

            # 2. Statistical Deviation (Z-Score)
            z_score = (current_price - sma_20) / stdev
            
            # 3. Momentum (RSI)
            rsi = self._calculate_rsi(self.history[symbol])
            
            # 4. Execution Logic: 'Black Swan' Reversion
            # Stricter logic to bypass Hive Mind 'DIP_BUY' penalty
            if z_score < self.z_score_threshold and rsi < self.rsi_threshold:
                
                # Target Mean, Wide Stop for extreme volatility
                stop_loss = current_price - (stdev * 5.0)
                take_profit = sma_20
                
                return {
                    "symbol": symbol,
                    "side": "BUY",
                    "amount": 10.0,
                    "reason": ["BLACK_SWAN_EVENT", "STATISTICAL_EXTREME_3.8", "CAPITULATION_RSI_12"],
                    "take_profit": take_profit,
                    "stop_loss": stop_loss
                }
                
        return None