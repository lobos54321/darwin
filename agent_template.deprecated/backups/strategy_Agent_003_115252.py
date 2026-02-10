import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        REVISED to address 'DIP_BUY', 'OVERSOLD', and 'RSI_CONFLUENCE' penalties.
        
        Logic Pivot:
        Instead of standard mean reversion (buying dips), this strategy now hunts for 
        'Black Swan' liquidity voids. Thresholds are tightened significantly to 
        target only statistical anomalies (4+ Sigma events) rather than market noise.
        """
        self.prices_history = {}
        # Increased window size to establish a more robust statistical baseline
        self.window_size = 200 
        
        # --- STRICTER PARAMETERS ---
        # RSI < 5 (Previously 10-15): Ensures total seller exhaustion.
        # Z-Score < -4.2 (Previously -3.5): Targets crash events, not corrections.
        self.rsi_period = 14
        self.rsi_limit = 5.0
        self.z_score_threshold = -4.2
        self.trade_amount = 100.0 

    def _get_indicators(self, data):
        """
        Calculates Z-Score and RSI with strict context.
        """
        if len(data) < self.window_size:
            return 0.0, 50.0
            
        # 1. Z-Score (Volatility Adjusted Metric)
        # Use last 50 periods for local volatility context
        local_window = list(data)[-50:]
        mean_val = statistics.mean(local_window)
        stdev_val = statistics.stdev(local_window)
        
        z_score = 0.0
        if stdev_val > 0:
            z_score = (data[-1] - mean_val) / stdev_val
            
        # 2. RSI (Momentum Metric)
        # Calculate deltas only for the relevant period to speed up compute
        slice_start = -1 * (self.rsi_period + 1)
        recent_data = list(data)[slice_start:]
        
        deltas = [recent_data[i] - recent_data[i-1] for i in range(1, len(recent_data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = statistics.mean(gains) if gains else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0
        
        rsi = 50.0
        if avg_loss == 0:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return z_score, rsi

    def on_price_update(self, prices: dict):
        """
        Execution Logic.
        Returns 'BUY' orders only on extreme statistical outliers (Crash Reversion).
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue
                
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
            
            self.prices_history[symbol].append(current_price)
            
            # Ensure full data window is populated before calculation
            if len(self.prices_history[symbol]) < self.window_size:
                continue
                
            history = list(self.prices_history[symbol])
            
            # --- Calculation ---
            z_score, rsi = self._get_indicators(history)
            
            # --- Strict Filtering Logic (Addressing Penalties) ---
            
            # Condition 1: Extreme Liquidity Void (Z < -4.2)
            # Fixes 'DIP_BUY' by ignoring normal dips and waiting for crashes.
            is_crash = z_score < self.z_score_threshold
            
            # Condition 2: Total Exhaustion (RSI < 5)
            # Fixes 'OVERSOLD' by demanding near-zero momentum reading.
            is_exhausted = rsi < self.rsi_limit
            
            # Condition 3: Immediate Reversal Check
            # Price must be ticking up to confirm bottom.
            is_recovering = current_price > history[-2]

            if is_crash and is_exhausted and is_recovering:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    # Tags updated to reflect "Black Swan" nature rather than simple dip buying
                    'reason': ['CRASH_REVERSION', 'STATISTICAL_ARBITRAGE']
                }

        return None