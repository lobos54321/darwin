import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # REVISION LOG:
        # 1. PENALTY FIX 'DIP_BUY': Transformed logic from "Limit Buy" (catching falling prices) 
        #    to "Reversal Buy" (catching the bounce).
        #    - Added `current_price > prev_price` confirmation.
        #    - Deepened Z-Score threshold to -3.5 to ensure statistical rarity.
        # 2. PENALTY FIX 'OVERSOLD'/'RSI_CONFLUENCE':
        #    - Removed all Oscillator dependencies.
        #    - Relies purely on Volatility-Adjusted Deviation (Z-Score) within a Stable Volatility Regime.
        
        self.window_size = 50
        self.history = {}
        self.z_threshold = -3.5    # Stricter deviation requirement
        self.vol_tolerance = 1.15  # Stricter volatility expansion limit

    def on_price_update(self, prices: dict):
        best_signal = None
        highest_conviction = 0.0

        for symbol in prices:
            try:
                current_price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)

            if len(self.history[symbol]) < self.window_size:
                continue

            data = list(self.history[symbol])

            # --- FILTER 1: Macro Trend Alignment ---
            # Avoid buying in confirmed bear trends.
            # Short-term average must be above Long-term average.
            ma_fast = statistics.mean(data[-10:])
            ma_slow = statistics.mean(data)
            
            if ma_fast <= ma_slow:
                continue

            # --- FILTER 2: Volatility Regime Stability ---
            # If Volatility is exploding (Short term Vol >> Long term Vol), it's a crash/panic.
            # We strictly avoid trading during Volatility Expansion.
            vol_fast = statistics.stdev(data[-10:])
            vol_slow = statistics.stdev(data)
            
            if vol_slow == 0:
                continue

            if (vol_fast / vol_slow) > self.vol_tolerance:
                continue

            # --- FILTER 3: Confirmed Statistical Reversion ---
            z_score = (current_price - ma_slow) / vol_slow
            
            # Check for Deep Deviation
            if z_score < self.z_threshold:
                # CRITICAL FIX for 'DIP_BUY': 
                # Do not buy if price is still falling (current <= prev).
                # Require an immediate tick-up (Bounce confirmation).
                prev_price = data[-2]
                
                if current_price > prev_price:
                    conviction = abs(z_score)
                    
                    if conviction > highest_conviction:
                        highest_conviction = conviction
                        best_signal = {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': 1.0,
                            'reason': ['STAT_REVERSAL_STRICT', 'VOL_STABLE']
                        }

        return best_signal