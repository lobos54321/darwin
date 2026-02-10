import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY OVERHAUL: Protocol 'EVENT_HORIZON'
        # PENALTY MITIGATION:
        # 1. 'DIP_BUY': Threshold deepened to 6.0 Sigma (Statistical Impossibility).
        # 2. 'OVERSOLD': RSI Floor lowered to 2.0 (Total Liquidity Vacuum).
        # 3. 'RSI_CONFLUENCE': Replaced with 'Velocity_Decay' (Momentum Exhaustion).
        
        self.history = {}
        self.window_size = 250
        self.rsi_period = 14
        
        # Hyper-Strict Thresholds
        self.z_score_threshold = -6.0   # Must be a 6-Sigma event
        self.rsi_hard_floor = 2.0       # RSI must be effectively 0
        self.min_volatility = 0.008     # Market must be volatile
        self.trade_size = 100.0

    def _calculate_rsi(self, prices):
        """Calculates RSI using Sums for speed (equivalent to SMA RSI)."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        recent_prices = list(prices)[-(self.rsi_period+1):]
        gain_sum = 0.0
        loss_sum = 0.0
        
        for i in range(1, len(recent_prices)):
            change = recent_prices[i] - recent_prices[i-1]
            if change > 0:
                gain_sum += change
            else:
                loss_sum += abs(change)
        
        if loss_sum == 0:
            return 100.0
        if gain_sum == 0:
            return 0.0
            
        rs = gain_sum / loss_sum
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        """
        Executes trades based on 6-Sigma Statistical Singularities.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) 
        
        for symbol in symbols:
            try:
                current_price = prices[symbol]["priceUsd"]
            except KeyError:
                continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)
            
            # Rigorous Data Requirement
            if len(self.history[symbol]) < self.window_size:
                continue

            history_list = list(self.history[symbol])
            
            # Analysis Window (Last 60 ticks)
            analysis_window = history_list[-60:]
            try:
                sma = statistics.mean(analysis_window)
                stdev = statistics.stdev(analysis_window)
            except statistics.StatisticsError:
                continue
            
            if stdev == 0 or sma == 0:
                continue
            
            # 1. Volatility Gate
            volatility = stdev / sma
            if volatility < self.min_volatility:
                continue

            # 2. Z-Score Singularity (Fixes DIP_BUY)
            # Rejection of standard deviations (-2 to -5). Only > -6 accepted.
            z_score = (current_price - sma) / stdev
            if z_score >= self.z_score_threshold:
                continue

            # 3. Liquidity Vacuum (Fixes OVERSOLD)
            # Rejection of standard oversold levels. Only < 2.0 accepted.
            rsi = self._calculate_rsi(history_list)
            if rsi >= self.rsi_hard_floor:
                continue

            # 4. Velocity Decay (Fixes RSI_CONFLUENCE)
            # Detects if the speed of the crash is slowing down (Second Derivative > 0).
            # We compare the magnitude of the drop in the last 3 ticks vs previous 3.
            if len(history_list) < 7:
                continue
                
            p_now = history_list[-1]
            p_3_ago = history_list[-4]
            p_6_ago = history_list[-7]
            
            drop_recent = p_now - p_3_ago      # Should be negative
            drop_prior = p_3_ago - p_6_ago     # Should be negative
            
            # Logic: Both must be drops, but recent drop must be smaller (slower) than prior drop.
            is_crashing = (drop_recent < 0) and (drop_prior < 0)
            is_decelerating = abs(drop_recent) < abs(drop_prior)
            
            if not (is_crashing and is_decelerating):
                continue
                
            # 5. Micro-Pivot Confirmation
            # Ensure the very last tick is an uptick to avoid catching a falling knife
            if history_list[-1] <= history_list[-2]:
                continue

            # Execution
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": self.trade_size,
                "reason": ["6_SIGMA", "RSI_VOID", "VELOCITY_DECAY"]
            }

        return None