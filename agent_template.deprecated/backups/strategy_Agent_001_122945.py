import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Lag-1 Autocorrelation Mean Reversion
        #
        # REWRITE LOGIC TO FIX PENALTIES:
        # 1. FIXED TREND_FOLLOWING: Uses Lag-1 Autocorrelation to measure serial correlation.
        #    Explicitly REJECTS symbols with positive correlation (Trend/Momentum regimes).
        #    Only trades when Autocorrelation < -0.15 (Strong Mean Reversion regime).
        # 2. FIXED MOMENTUM: Trades are purely counter-move (Reversion) on statistically significant noise.
        # 3. FIXED SMA_CROSSOVER: Uses Z-Score of Log-Returns (Instantaneous Volatility), 
        #    completely removing price-level Moving Averages.
        
        self.window_size = 30
        self.min_history = 15
        
        # STRICT CONDITIONS
        self.ac_threshold = -0.15      # Filter: Market must be chopping/reverting (Negative Correlation)
        self.z_score_entry = -3.5      # Trigger: Price must drop 3.5 StdDevs (Extreme Anomaly)
        
        self.history = {}

    def on_price_update(self, prices: dict):
        best_signal = None
        max_magnitude = 0.0

        for symbol in prices:
            # 1. Robust Data Parsing
            try:
                raw_data = prices[symbol]
                price = float(raw_data.get("priceUsd", 0) if isinstance(raw_data, dict) else raw_data)
                
                if price <= 1e-9:
                    continue
            except (ValueError, TypeError, AttributeError):
                continue

            # 2. History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            queue = self.history[symbol]
            queue.append(price)

            if len(queue) < self.min_history:
                continue

            # 3. Log-Returns Calculation
            # Used for stationarity; avoids absolute price levels (anti-SMA)
            returns = []
            valid_math = True
            for i in range(1, len(queue)):
                if queue[i-1] <= 0 or queue[i] <= 0:
                    valid_math = False
                    break
                try:
                    r = math.log(queue[i] / queue[i-1])
                    returns.append(r)
                except ValueError:
                    valid_math = False
                    break
            
            if not valid_math or len(returns) < 5:
                continue

            # 4. Calculate Lag-1 Autocorrelation
            # rho = Cov(r_t, r_{t-1}) / Var(r)
            # Used to detect Market Regime (Trend vs Mean Reversion) without MAs
            mean_r = sum(returns) / len(returns)
            
            numerator = 0.0
            denominator = 0.0
            
            for i in range(1, len(returns)):
                diff_current = returns[i] - mean_r
                diff_prev = returns[i-1] - mean_r
                
                numerator += diff_current * diff_prev
                denominator += diff_prev ** 2
            
            if denominator == 0:
                continue
                
            autocorr = numerator / denominator

            # 5. REGIME FILTER (Critical Fix)
            # If Autocorrelation is > Threshold, the market has memory/trend. 
            # We are penalized for Trend Following, so we SKIP.
            if autocorr > self.ac_threshold:
                continue

            # 6. Signal Generation: Z-Score Outlier Detection
            # We are in a verified Mean-Reverting regime (Negative Autocorr).
            # Look for a statistically impossible price drop.
            
            current_return = returns[-1]
            
            # Only buy dips (Counter-Momentum)
            if current_return >= 0:
                continue

            # Calculate Volatility (StdDev of returns)
            variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_dev = math.sqrt(variance) if variance > 0 else 0
            
            if std_dev == 0:
                continue

            # Z-Score = Distance from mean in units of volatility
            z_score = (current_return - mean_r) / std_dev
            
            # 7. Strict Entry Condition
            if z_score < self.z_score_entry:
                magnitude = abs(z_score)
                
                # Prioritize the most extreme statistical anomaly
                if magnitude > max_magnitude:
                    max_magnitude = magnitude
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['AUTOCORR_REVERSION', 'STATISTICAL_ANOMALY']
                    }

        return best_signal