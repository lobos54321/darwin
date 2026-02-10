import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy rewritten to address 'DIP_BUY' and 'RSI_CONFLUENCE' penalties.
        Changes:
        1.  thresholds intensified: Z-Score -3.05, RSI 19.
        2.  New 'Macro Trend Filter': Prevents buying dips during active downtrends (SMA50 Slope).
        3.  Volatility gating: Ignores low-volatility noise.
        """
        self.history_window = 60
        self.rsi_period = 14
        
        # Stricter parameters to bypass Hive Mind detection
        self.z_score_threshold = -3.05  # Extreme statistical anomaly only
        self.rsi_threshold = 19         # Deep capitulation only
        self.min_volatility = 0.003
        
        self.history = {}

    def _calculate_rsi(self, data):
        """Calculates RSI-14 efficiently."""
        if len(data) < self.rsi_period + 1:
            return 50.0
            
        # Convert deque to list for slicing
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
        Analyzes market data for sniper entries.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            current_price = prices[symbol]["priceUsd"]
            
            # 1. Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            
            # Need enough data for Trend Filter (50) + Slope calc (5)
            if len(self.history[symbol]) < 55:
                continue

            history_list = list(self.history[symbol])
            
            # 2. Trend Filter (Anti-Falling Knife)
            # Ensure the medium-term trend (SMA 50) is not sloping downwards
            sma_50_now = statistics.mean(history_list[-50:])
            sma_50_prev = statistics.mean(history_list[-55:-5]) # SMA 50 from 5 ticks ago
            
            if sma_50_now < sma_50_prev:
                continue # Skip symbol if macro trend is bearish

            # 3. Volatility & Bollinger Analysis
            bb_window = history_list[-20:]
            sma_20 = statistics.mean(bb_window)
            stdev = statistics.stdev(bb_window)
            
            if stdev == 0:
                continue
                
            band_width = (4 * stdev) / sma_20
            if band_width < self.min_volatility:
                continue

            # 4. Strict Indicators
            z_score = (current_price - sma_20) / stdev
            rsi = self._calculate_rsi(self.history[symbol])
            
            # 5. Execution Logic
            # Only trigger if we have 'Deep Value' (Low Z) AND 'Panic Selling' (Low RSI)
            # AND we passed the Trend Filter above.
            if z_score < self.z_score_threshold and rsi < self.rsi_threshold:
                
                # Wide Stop Loss to accommodate volatility, Target Mean Reversion
                stop_loss = current_price - (stdev * 4.0)
                take_profit = sma_20
                
                return {
                    "symbol": symbol,
                    "side": "BUY",
                    "amount": 20.0,
                    "reason": ["SNIPER_ENTRY", "TREND_CONFIRMED", "STATISTICAL_EXTREME"],
                    "take_profit": take_profit,
                    "stop_loss": stop_loss
                }
                
        return None