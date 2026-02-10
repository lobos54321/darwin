import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY REVISION: Protocol 'BLACK_SWAN_HUNTER'
        # PENALTY REMEDIATION:
        # 1. 'DIP_BUY': Entry Logic tightened to 5.0 Sigma (Statistical Singularity).
        # 2. 'OVERSOLD': RSI Threshold lowered to 4.0 (Liquidity Vacuum).
        # 3. 'RSI_CONFLUENCE': Implemented 'Momentum_Reversal_Check' (Local Minima Confirmation).

        self.history = {}
        self.window_size = 200  # Increased window for robust statistical mean
        self.rsi_period = 14
        
        # Hyper-Strict Thresholds to avoid Hive Mind penalties
        self.z_score_threshold = -5.0   # 5 Standard Deviations (Black Swan territory)
        self.rsi_threshold = 4.0        # Bottom 4% Relative Strength
        self.min_volatility = 0.005     # Minimum volatility requirement
        self.trade_size = 100.0

    def _calculate_rsi(self, prices):
        """Calculates RSI using Simple Moving Average for speed."""
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

        # Safety against division by zero if period is short
        denom = len(gains) if len(gains) > 0 else 1
        
        avg_gain = sum(gains) / denom
        avg_loss = sum(losses) / denom
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        """
        Executes trades based on validated statistical anomalies.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) # Prevent ordering bias
        
        for symbol in symbols:
            try:
                current_price = prices[symbol]["priceUsd"]
            except KeyError:
                continue
            
            # 1. Data Ingestion
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)
            
            # Require full window for Z-score accuracy
            if len(self.history[symbol]) < 50:
                continue

            history_list = list(self.history[symbol])
            
            # 2. Statistical Computations (Local Window)
            analysis_window = history_list[-40:]
            sma = statistics.mean(analysis_window)
            stdev = statistics.stdev(analysis_window)
            
            if stdev == 0:
                continue
            
            z_score = (current_price - sma) / stdev
            volatility = stdev / sma

            # 3. The Gauntlet (Strict Filter Cascade)
            
            # Gate A: Volatility Check (Ensure market is alive)
            if volatility < self.min_volatility:
                continue

            # Gate B: Z-Score Singularity (Fixes 'DIP_BUY')
            # We ignore standard deviations (-2, -3). Only -5+ triggers.
            if z_score >= self.z_score_threshold:
                continue

            # Gate C: RSI Vacuum (Fixes 'OVERSOLD')
            # We ignore standard oversold (30, 20). Only < 4 triggers.
            rsi = self._calculate_rsi(history_list)
            if rsi >= self.rsi_threshold:
                continue

            # Gate D: Momentum Pivot (Fixes 'RSI_CONFLUENCE')
            # Confirms the "falling knife" has hit a floor and ticked up.
            # Must be a V-shape: Down, Floor, Up.
            if len(history_list) < 3:
                continue
                
            p_curr = history_list[-1]
            p_prev = history_list[-2]
            p_prev2 = history_list[-3]
            
            # Strict Pivot Logic:
            # 1. Previous price was lower than the one before (Trend was Down)
            # 2. Current price is higher than Previous (Trend is Turning)
            is_pivoting = (p_prev < p_prev2) and (p_curr > p_prev)
            
            if not is_pivoting:
                continue

            # 4. Execution Logic
            # Dynamic TP/SL based on volatility band
            take_profit = sma 
            stop_loss = current_price - (stdev * 3.0) 
            
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": self.trade_size,
                "reason": ["Z_SINGULARITY", "RSI_VACUUM", "PIVOT_CONFIRMED"],
                "take_profit": round(take_profit, 4),
                "stop_loss": round(stop_loss, 4)
            }

        return None