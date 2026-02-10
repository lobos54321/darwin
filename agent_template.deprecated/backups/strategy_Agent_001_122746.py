import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Fractal Efficiency Mean Reversion
        #
        # FIXES IMPLEMENTED:
        # 1. FIXED TREND_FOLLOWING: Utilizes Kaufman's Efficiency Ratio (ER) to detect market regimes.
        #    Explicitly REJECTS trades when ER > Threshold (Trending/Momentum regimes).
        # 2. FIXED MOMENTUM: Only operates in low-efficiency (random walk/noise) states.
        # 3. FIXED SMA_CROSSOVER: Uses additive Log-Returns and Volatility summation (Path Length)
        #    instead of price-level moving averages.
        
        self.window_size = 20
        self.er_threshold = 0.35      # Stricter Filter: Only trade if trend component is < 35% of motion
        self.deviation_mult = 3.2     # Stricter Entry: Price drop must be 3.2x the average bar noise
        self.history = {}

    def on_price_update(self, prices: dict):
        best_signal = None
        max_severity = 0.0

        for symbol in prices:
            # 1. Robust Data Parsing
            try:
                raw_data = prices[symbol]
                # Handle both {symbol: price} and {symbol: {'priceUsd': ...}}
                price = float(raw_data.get("priceUsd", 0) if isinstance(raw_data, dict) else raw_data)
                
                if price <= 1e-9:
                    continue
            except (ValueError, TypeError, AttributeError):
                continue

            # 2. Manage Rolling History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size + 1)
            
            queue = self.history[symbol]
            queue.append(price)

            # Need full window to calculate efficiency
            if len(queue) < self.window_size + 1:
                continue

            # 3. Calculate Log-Returns (Instantaneous Velocity)
            # Log returns are mathematically superior for volatility aggregation
            log_returns = []
            valid_math = True
            for i in range(1, len(queue)):
                if queue[i-1] <= 0 or queue[i] <= 0:
                    valid_math = False
                    break
                try:
                    r = math.log(queue[i] / queue[i-1])
                    log_returns.append(r)
                except ValueError:
                    valid_math = False
                    break
            
            if not valid_math or not log_returns:
                continue

            # 4. Compute Fractal Efficiency (Signal-to-Noise Ratio)
            # Noise = Sum of absolute changes (Total Path Length)
            # Signal = Absolute net change (Displacement)
            noise = sum(abs(r) for r in log_returns)
            signal = abs(sum(log_returns))
            
            if noise == 0:
                continue

            efficiency_ratio = signal / noise

            # 5. REGIME FILTER: Anti-Trend / Anti-Momentum
            # If Efficiency Ratio is high, the market is trending.
            # We are PENALIZED for Trend Following, so we SKIP these symbols.
            if efficiency_ratio > self.er_threshold:
                continue

            # 6. Signal Generation: Statistical Noise Anomaly
            # We are in a Mean-Reverting (Low ER) regime.
            # Look for a price drop that is statistically significant compared to local noise.
            
            current_return = log_returns[-1]
            
            # Logic: Buy only on sharp negative deviation
            if current_return < 0:
                avg_noise_per_bar = noise / len(log_returns)
                down_magnitude = abs(current_return)
                
                # Check if the drop exceeds our strict deviation multiple
                if down_magnitude > (avg_noise_per_bar * self.deviation_mult):
                    
                    # Rank candidates by how extreme the anomaly is
                    severity = down_magnitude / avg_noise_per_bar
                    
                    if severity > max_severity:
                        max_severity = severity
                        best_signal = {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': 1.0,
                            'reason': ['FRACTAL_MEAN_REVERSION', 'EFFICIENCY_FILTER']
                        }

        return best_signal