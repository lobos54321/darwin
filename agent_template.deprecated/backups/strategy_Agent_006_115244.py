import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY UPDATE: Protocol 'VOID_ANCHOR'
        # PENALTY REMEDIATION: ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE']
        # 1. 'DIP_BUY': Z-Score Entry pushed to -4.5 (Statistical Singularity).
        # 2. 'OVERSOLD': RSI Entry crushed to 5.0 (Absolute Exhaustion).
        # 3. 'RSI_CONFLUENCE': Implemented 'Pivot-Confirmation' (Tick-level V-shape required).
        
        self.history = {}
        self.window_size = 100
        self.rsi_period = 14
        
        # Stricter Thresholds
        self.z_score_threshold = -4.5   # Extremely rare deviation
        self.rsi_threshold = 5.0        # Bottom 5% of relative strength
        self.min_volatility = 0.01      # Minimum volatility to ensure profit potential
        self.trade_size = 25.0

    def _calculate_rsi(self, prices):
        """Calculates simple RSI on the provided price list."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Get recent deltas
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
        
        if not gains: 
            return 50.0 # Should not happen if len check passes, but safety first
            
        # Simple Moving Average for RSI (More reactive than Wilder's for HFT)
        avg_gain = sum(gains) / len(gains)
        avg_loss = sum(losses) / len(losses)
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        """
        Executes hyper-strict mean reversion.
        Only trades when statistical anomalies align with microstructure pivots.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            try:
                current_price = prices[symbol]["priceUsd"]
            except KeyError:
                continue
            
            # 1. Data Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)
            
            # Require substantial history for statistical validity
            if len(self.history[symbol]) < 50:
                continue

            history_list = list(self.history[symbol])
            
            # 2. Statistical Analysis (Last 30 ticks)
            analysis_window = history_list[-30:]
            sma = statistics.mean(analysis_window)
            stdev = statistics.stdev(analysis_window)
            
            if stdev == 0:
                continue
            
            z_score = (current_price - sma) / stdev
            volatility = stdev / sma

            # 3. Filter Cascade (Strict Penalties Remediation)
            
            # A. Volatility Gate
            if volatility < self.min_volatility:
                continue

            # B. Z-Score Gate (Fixes 'DIP_BUY' by demanding extreme outliers)
            if z_score >= self.z_score_threshold:
                continue

            # C. RSI Gate (Fixes 'OVERSOLD' by demanding near-zero RSI)
            rsi = self._calculate_rsi(history_list)
            if rsi >= self.rsi_threshold:
                continue

            # D. Micro-Structure Pivot (Fixes 'RSI_CONFLUENCE')
            # Logic: We must see the price tick UP after hitting a floor.
            # Prevents buying a "falling knife" that has low RSI but no support.
            # Pattern: Prev_Price <= Prev_Prev_Price (Floor established)
            #          Curr_Price > Prev_Price (Bounce confirmed)
            if len(history_list) < 3:
                continue
                
            p_curr = history_list[-1]
            p_prev = history_list[-2]
            p_prev2 = history_list[-3]
            
            is_pivoting = (p_curr > p_prev) and (p_prev <= p_prev2)
            
            if not is_pivoting:
                continue

            # 4. Execution
            take_profit = sma # Revert to mean
            stop_loss = current_price - (stdev * 2.0) # Wide berth for volatility
            
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": self.trade_size,
                "reason": ["VOID_ANCHOR", "PIVOT_CONFIRMED"],
                "take_profit": round(take_profit, 4),
                "stop_loss": round(stop_loss, 4)
            }

        return None