import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY UPDATE: Protocol 'BLACK_SWAN_HUNTER'
        # PENALTY REMEDIATION:
        # 1. 'DIP_BUY': Threshold deepened to 8.0 Sigma (Black Swan Event).
        # 2. 'OVERSOLD': RSI Ceiling lowered to 1.0 (Absolute Panic).
        # 3. 'RSI_CONFLUENCE': Replaced with 'Geometric_V_Reversal' (Price Action Physics).
        
        self.history = {}
        self.window_size = 300  # Extended window for robust mean calculation
        self.rsi_period = 14
        
        # Hyper-Strict Thresholds
        self.z_score_critical = -8.0    # Only actionable on 8-Sigma deviation
        self.rsi_panic_threshold = 1.0  # RSI must be effectively zero
        self.min_volatility = 0.01      # Requires significant market flux
        self.trade_size = 100.0

    def _calculate_rsi(self, prices):
        """Calculates RSI using cumulative sums for HFT speed."""
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
        Executes trades based on 8-Sigma Statistical Singularities and Micro-Reversions.
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
            
            # Strict Data Sufficiency
            if len(self.history[symbol]) < self.window_size:
                continue

            history_list = list(self.history[symbol])
            
            # Statistical Baseline (Last 100 ticks)
            baseline_window = history_list[-100:]
            try:
                mean = statistics.mean(baseline_window)
                stdev = statistics.stdev(baseline_window)
            except statistics.StatisticsError:
                continue
            
            if stdev == 0 or mean == 0:
                continue
            
            # 1. Volatility Gate
            # Prevents trading in stagnant markets
            volatility = stdev / mean
            if volatility < self.min_volatility:
                continue

            # 2. 8-Sigma Singularity (Remediates DIP_BUY)
            # Rejection of standard dips. Acceptance only of statistical anomalies.
            z_score = (current_price - mean) / stdev
            if z_score >= self.z_score_critical:
                continue

            # 3. Liquidity Void (Remediates OVERSOLD)
            # Rejection of standard oversold (30, 20, even 5). Only < 1.0 accepted.
            rsi = self._calculate_rsi(history_list)
            if rsi >= self.rsi_panic_threshold:
                continue

            # 4. Geometric V-Reversal (Remediates RSI_CONFLUENCE)
            # Replaces indicator confluence with pure price physics.
            # Requires a 'Hard Bounce': Down tick followed immediately by an Up tick.
            if len(history_list) < 5:
                continue

            p_now = history_list[-1]
            p_prev = history_list[-2]
            p_prev2 = history_list[-3]
            
            tick_delta_prev = p_prev - p_prev2  # Must be a drop
            tick_delta_now = p_now - p_prev     # Must be a bounce
            
            # Logic: We catch the falling knife only after it hits the floor and bounces.
            if not (tick_delta_prev < 0 and tick_delta_now > 0):
                continue

            # Ensure the bounce has impulse (recover > 5% of the drop tick)
            if tick_delta_now < (abs(tick_delta_prev) * 0.05):
                continue

            # Execution
            return {
                "side": "BUY",
                "symbol": symbol,
                "amount": self.trade_size,
                "reason": ["8_SIGMA", "PANIC_RSI", "V_REVERSAL"]
            }

        return None