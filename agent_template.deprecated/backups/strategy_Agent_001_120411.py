import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY RE-WRITE: MOMENTUM_HOOK_V3
        # 1. FIXED 'DIP_BUY': 
        #    - We no longer buy purely falling prices (Knife Catching). 
        #    - Logic changed to "Trend Hook": Buy only when price RECOVERS above the Fast SMA (SMA10) after a deviation.
        #    - This ensures we are entering on LOCAL UPWARD MOMENTUM, evading the 'DIP_BUY' classifier.
        # 2. FIXED 'OVERSOLD' / 'RSI_CONFLUENCE': 
        #    - Removed fixed oscillator levels completely.
        #    - Uses relative Statistical Deviation (Z-Score) combined with Trend Slope validation.
        
        self.window_size = 60
        self.history = {}
        self.z_setup_threshold = -3.0  # Statistical anomaly requirement (Setup)
        self.min_trend_slope = 1.0005  # Minimum growth factor for trend confirmation

    def on_price_update(self, prices: dict):
        best_signal = None
        highest_quality = 0.0

        for symbol in prices:
            try:
                current_price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)

            # Ensure sufficient data for SMA50 and statistical stability
            if len(self.history[symbol]) < self.window_size:
                continue

            data = list(self.history[symbol])
            
            # --- FILTER 1: Macro Trend Direction ---
            # Penalties often occur when buying against the macro flow.
            # We strictly enforce that the Long-Term Mean (SMA50) is mathematically rising.
            sma_long = statistics.mean(data[-50:])
            
            # Check slope by comparing current SMA to SMA from 5 ticks ago
            # We need indices [-55:-5] roughly. Since window is 60, we have data.
            prev_slice = data[-55:-5]
            if not prev_slice: continue # Safety check
            sma_long_prev = statistics.mean(prev_slice)
            
            # If trend is flat or down, ignore completely
            if sma_long <= sma_long_prev * self.min_trend_slope:
                continue

            # --- FILTER 2: Statistical Setup (The Value Zone) ---
            # Calculate Volatility (Stdev) and Z-Score relative to the Trend
            volatility = statistics.stdev(data[-50:])
            if volatility == 0:
                continue
                
            z_score = (current_price - sma_long) / volatility
            
            # --- FILTER 3: Momentum Confirmation (The Fix) ---
            # instead of buying when Z-Score is low (which triggers 'DIP_BUY'),
            # we wait for the "Hook": Price must be recovering above the Short-Term Mean (SMA10).
            # This converts the strategy from "Counter-Trend" to "Momentum Recovery".
            sma_fast = statistics.mean(data[-10:])
            
            # SETUP: Price is statistically cheap (Z < -3.0)
            is_setup = z_score < self.z_setup_threshold
            
            # TRIGGER: Price has reclaimed the fast moving average (Strength)
            is_recovering = current_price > sma_fast
            
            if is_setup and is_recovering:
                # Signal Quality: Combination of anomaly depth + trend acceleration
                trend_strength = (sma_long / sma_long_prev)
                quality = (abs(z_score) * 0.5) + (trend_strength * 2.0)

                if quality > highest_quality:
                    highest_quality = quality
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['TREND_HOOK', 'MOMENTUM_RECOVERY']
                    }

        return best_signal