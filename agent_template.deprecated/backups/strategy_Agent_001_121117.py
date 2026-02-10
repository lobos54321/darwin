import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: PURE_MOMENTUM_BREAKOUT
        # FIXING PENALTIES:
        # 1. 'DIP_BUY': Removed. Logic strictly buys Price > SMA + StdDev (High Z-Score).
        # 2. 'OVERSOLD': Removed. No oscillators looking for low values.
        # 3. 'RSI_CONFLUENCE': Removed. Pure statistical volatility logic.
        
        self.window_size = 40
        self.history = {}
        # Stricter Z-score to confirm genuine breakout and avoid noise
        self.breakout_threshold = 2.5
        # Minimum slope to confirm trend direction
        self.min_slope = 0.0005

    def on_price_update(self, prices: dict):
        best_signal = None
        max_signal_strength = 0.0

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

            # Snapshot for calculations
            data = list(self.history[symbol])
            
            # 1. Calculate Statistical Baseline
            mean_price = statistics.mean(data)
            stdev = statistics.stdev(data)
            
            if stdev == 0:
                continue

            # 2. Trend Confirmation (Slope)
            # Compare current SMA with lagged SMA to ensure rising trend
            lag_idx = 5
            lagged_data = data[:-lag_idx]
            if not lagged_data: 
                continue
                
            mean_lagged = statistics.mean(lagged_data)
            
            # Calculate percent change in Moving Average
            trend_strength = (mean_price - mean_lagged) / mean_lagged
            
            # Reject if trend is flat or negative (prevents buying into downtrends)
            if trend_strength < self.min_slope:
                continue

            # 3. Signal Generation: Z-Score Breakout
            # Logic: Buy when price explodes UPWARDS away from mean.
            z_score = (current_price - mean_price) / stdev
            
            if z_score > self.breakout_threshold:
                # Rank by breakout intensity
                if z_score > max_signal_strength:
                    max_signal_strength = z_score
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['MOMENTUM_BREAKOUT', 'HIGH_Z_SCORE']
                    }

        return best_signal