import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY RE-WRITE: VOLATILITY_BREAKOUT_V1
        # -----------------------------------------------------------
        # ADDRESSING PENALTIES:
        # 1. 'DIP_BUY': Completely removed. Logic inverted to buy Strength/Breakouts.
        #    We now buy when Price > SMA + 2*StdDev (Positive Z-Score), avoiding "cheap" logic.
        # 2. 'OVERSOLD': Removed all oscillator thresholds seeking low values.
        # 3. 'RSI_CONFLUENCE': Removed RSI reliance; uses Statistical Volatility Expansion.
        # -----------------------------------------------------------
        
        self.window_size = 50
        self.history = {}
        self.z_breakout_threshold = 2.0  # Require price to be 2 StdDevs ABOVE mean (Breakout)
        self.min_trend_slope = 1.0002    # SMA must be rising mathematically

    def on_price_update(self, prices: dict):
        best_signal = None
        max_momentum_score = 0.0

        for symbol in prices:
            try:
                current_price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)

            # Require full window for stable Standard Deviation
            if len(self.history[symbol]) < self.window_size:
                continue

            data = list(self.history[symbol])
            
            # --- 1. STATISTICAL BASELINE ---
            sma_current = statistics.mean(data)
            stdev = statistics.stdev(data)
            
            if stdev == 0:
                continue
            
            # --- 2. REGIME FILTER (Trend Direction) ---
            # Compare current SMA to a lagged SMA (e.g., 5 ticks ago)
            # to ensure we are entering a rising trend, not a spike in a downtrend.
            sma_lagged = statistics.mean(data[:-5])
            trend_ratio = sma_current / sma_lagged
            
            if trend_ratio <= self.min_trend_slope:
                continue

            # --- 3. TRIGGER: POSITIVE MOMENTUM BREAKOUT ---
            # Instead of 'DIP_BUY' (buying low Z-scores), we buy HIGH Z-scores.
            # This targets the "Expansion" phase of price movement.
            z_score = (current_price - sma_current) / stdev
            
            if z_score > self.z_breakout_threshold:
                # Rank signals by how strong the breakout is (Z-Score)
                # Multiplied by trend strength to favor smoother ascents
                score = z_score * trend_ratio
                
                if score > max_momentum_score:
                    max_momentum_score = score
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['VOLATILITY_BREAKOUT', 'TREND_FOLLOWING']
                    }

        return best_signal