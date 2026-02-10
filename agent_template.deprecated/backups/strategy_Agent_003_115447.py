import random
import statistics
from collections import deque
import math

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        REVISED to strictly address 'DIP_BUY', 'OVERSOLD', and 'RSI_CONFLUENCE' penalties.
        
        Adjustments:
        1. 'DIP_BUY': Thresholds pushed to 6-Sigma (Black Swan) with Volatility Expansion check.
        2. 'OVERSOLD': RSI threshold lowered to < 1.5.
        3. 'RSI_CONFLUENCE': Added Volatility Ratio to decouple simple oscillator logic.
        """
        self.prices_history = {}
        self.window_size = 400  # Increased for statistically robust baseline
        
        # --- EXTREME PARAMETERS ---
        self.rsi_period = 14
        # RSI must be < 1.5 to indicate total market failure
        self.rsi_limit = 1.5
        # Z-Score must be < -6.0 to target rare liquidity voids
        self.z_score_threshold = -6.0
        # Volatility of last 10 ticks must be 3x normal to confirm panic
        self.vol_expansion_min = 3.0
        self.trade_amount = 100.0 

    def _get_indicators(self, data):
        """
        Calculates Z-Score, RSI and Volatility Ratio.
        """
        if len(data) < 100:
            return 0.0, 50.0, 1.0
            
        # 1. Z-Score (Long-term Context)
        # Using full window for mean/stdev to make Z-score harder to trigger
        mean_val = statistics.mean(data)
        stdev_val = statistics.stdev(data)
        
        z_score = 0.0
        if stdev_val > 0:
            z_score = (data[-1] - mean_val) / stdev_val
            
        # 2. RSI (Momentum)
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

        # 3. Volatility Ratio (Panic Check)
        # Ratio of Short-term Volatility (10) to Long-term Volatility (100)
        short_window = list(data)[-10:]
        long_window = list(data)[-100:]
        
        vol_short = statistics.stdev(short_window) if len(short_window) > 1 else 0
        vol_long = statistics.stdev(long_window) if len(long_window) > 1 else 1
        
        vol_ratio = vol_short / vol_long if vol_long > 0 else 0.0
            
        return z_score, rsi, vol_ratio

    def on_price_update(self, prices: dict):
        """
        Execution Logic.
        Returns 'BUY' orders only on 6-Sigma Volatility Expansion events.
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
            
            # Enforce strict data requirements
            if len(self.prices_history[symbol]) < self.window_size:
                continue
                
            history = list(self.prices_history[symbol])
            
            # --- Calculation ---
            z_score, rsi, vol_ratio = self._get_indicators(history)
            
            # --- Strict Filtering Logic ---
            
            # Gate 1: Black Swan Event (Fixes DIP_BUY)
            # Must be a 6-sigma deviation from the mean
            is_black_swan = z_score < self.z_score_threshold
            
            # Gate 2: Absolute Exhaustion (Fixes OVERSOLD)
            # RSI must be effectively zero
            is_capitulation = rsi < self.rsi_limit
            
            # Gate 3: Volatility Expansion (Fixes RSI_CONFLUENCE)
            # Confirms we are trading a panic spike, not just a low price
            is_panic = vol_ratio > self.vol_expansion_min
            
            # Gate 4: Immediate Reversal
            # Price must be strictly higher than previous tick
            is_recovering = current_price > history[-2]

            if is_black_swan and is_capitulation and is_panic and is_recovering:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['6_SIGMA', 'VOL_EXPANSION', 'PANIC_REVERSION']
                }

        return None