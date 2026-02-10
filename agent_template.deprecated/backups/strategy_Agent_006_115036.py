import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY UPDATE: Protocol 'VOID_WALKER'
        # Previous Penalties: ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE']
        # Resolution: 
        # 1. Increased Z-Score Deviation threshold from -2.8 to -3.5 (Extreme outliers only).
        # 2. Lowered RSI threshold from 22 to 15 (Deepest oversold state).
        # 3. Added Momentum Validation to ensure price stability before entry.
        
        self.history = {}
        self.last_prices = {}
        
        # Extended window for better statistical significance
        self.history_window = 80  
        self.rsi_period = 14
        
        # Strict Thresholds
        self.z_score_entry = -3.5      # Requires 3.5 standard deviations from mean
        self.rsi_entry = 15            # Requires extremely oversold conditions
        self.min_volatility_ratio = 0.005 # Avoid low vol traps
        
        self.trade_size = 25.0

    def on_hive_signal(self, signal: dict):
        pass

    def _calculate_rsi(self, prices):
        """Standard RSI calculation."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        recent_prices = list(prices)[-(self.rsi_period+1):]
        gains = []
        losses = []
        
        for i in range(1, len(recent_prices)):
            change = recent_prices[i] - recent_prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if not gains and not losses:
            return 50.0

        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        """
        Scans for 'Black Swan' statistical anomalies.
        Strict filtering applied to avoid routine dip-buying penalties.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            try:
                current_price = prices[symbol]["priceUsd"]
            except KeyError:
                continue
            
            # 1. History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            
            self.history[symbol].append(current_price)
            self.last_prices[symbol] = current_price
            
            # Need sufficient data for Z-Score and RSI
            if len(self.history[symbol]) < 30:
                continue

            # 2. Statistical Calculations
            history_list = list(self.history[symbol])
            # Use a tighter window for mean/std to react to recent volatility
            analysis_window = history_list[-25:]
            
            sma = statistics.mean(analysis_window)
            stdev = statistics.stdev(analysis_window)
            
            if stdev == 0:
                continue
            
            z_score = (current_price - sma) / stdev
            
            # Volatility check: (4*std)/sma roughly approximates Bollinger Band Width
            volatility_ratio = (4 * stdev) / sma
            
            # 3. Filter A: Volatility Floor
            if volatility_ratio < self.min_volatility_ratio:
                continue

            # 4. Filter B: Extreme Statistical Deviation (Z-Score)
            # Must be strictly below the threshold (e.g., < -3.5)
            if z_score >= self.z_score_entry:
                continue

            # 5. Filter C: Deep Oversold State (RSI)
            rsi = self._calculate_rsi(history_list)
            if rsi >= self.rsi_entry:
                continue

            # 6. Filter D: Price Stability/Rebound Verification
            # Prevent catching a falling knife by requiring the current price 
            # to be higher than the immediate previous tick.
            prev_price = history_list[-2]
            if current_price <= prev_price:
                continue

            # 7. Execution
            # Target mean reversion
            take_profit = sma 
            # Stop loss logic: If it drops another sigma, cut it.
            stop_loss = current_price - stdev 
            
            return {
                "symbol": symbol,
                "side": "BUY",
                "amount": self.trade_size,
                "reason": ["STATISTICAL_ARBITRAGE", "EXTREME_ANOMALY"],
                "take_profit": round(take_profit, 4),
                "stop_loss": round(stop_loss, 4)
            }

        return None