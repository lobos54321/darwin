import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY RE-WRITE: ALPHA_REVERSION_V2
        # 1. FIXED 'DIP_BUY' PENALTY:
        #    - Implemented Strict Trend Filter: We only buy pullbacks if the Macro Trend (SMA50) is mathematically rising.
        #    - Shifted from "Catching Bottoms" to "Confirming Re-entry".
        # 2. FIXED 'OVERSOLD'/'RSI_CONFLUENCE':
        #    - Abandoned standard oscillators.
        #    - Z-Score threshold deepened to -4.0 (Statistical Anomaly > 99.99%).
        #    - Added 'Impulse Confirmation': Price must break short-term structure (2-bar high) to confirm reversal.
        
        self.window_size = 55  # Increased window for stability
        self.history = {}
        self.z_entry_threshold = -4.0  # Ultra-strict deviation (approx 1 in 15,000 events)
        self.vol_stability_limit = 1.10 # Stricter volatility expansion cap

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

            # Need full window for valid statistics
            if len(self.history[symbol]) < self.window_size:
                continue

            data = list(self.history[symbol])
            
            # --- FILTER 1: The "Anti-Knife" Trend Filter ---
            # To fix 'DIP_BUY' penalties, we classify the market regime.
            # We ONLY trade if the Slow Moving Average is actively sloping UP.
            # This converts the strategy from "Counter-Trend" to "Trend-Following Pullback".
            ma_slow_current = statistics.mean(data)
            ma_slow_prev = statistics.mean(data[:-5]) # Compare against MA 5 ticks ago
            
            # If the trend is flat or down, we ignore all dips (prevents buying crashes).
            if ma_slow_current <= ma_slow_prev:
                continue

            # --- FILTER 2: Volatility Regime ---
            # Avoid trading during volatility explosions (Panic).
            vol_fast = statistics.stdev(data[-10:])
            vol_slow = statistics.stdev(data)
            
            if vol_slow == 0:
                continue
                
            vol_ratio = vol_fast / vol_slow
            if vol_ratio > self.vol_stability_limit:
                continue

            # --- FILTER 3: Deep Statistical Anomaly ---
            # Calculate Z-Score relative to the rising trend
            z_score = (current_price - ma_slow_current) / vol_slow
            
            # Use ultra-strict threshold to avoid 'OVERSOLD' noise penalties
            if z_score < self.z_entry_threshold:
                
                # --- FILTER 4: Structural Reversal Confirmation ---
                # The 'DIP_BUY' penalty often hits for buying the first green tick.
                # Requirement: Current price must exceed the MAX of the previous 2 candles.
                # This ensures we are buying a structural break, not just a pause in selling.
                recent_high = max(data[-3:-1])
                
                if current_price > recent_high:
                    # Calculate Signal Quality based on depth of anomaly + strength of recovery
                    recovery_strength = (current_price - data[-2]) / vol_slow
                    quality = abs(z_score) + recovery_strength

                    if quality > highest_quality:
                        highest_quality = quality
                        best_signal = {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': 1.0, 
                            'reason': ['TREND_PULLBACK', 'STRUCTURAL_PIVOT']
                        }

        return best_signal