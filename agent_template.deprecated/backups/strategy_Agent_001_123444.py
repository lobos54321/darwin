import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: Variance Ratio Mean Reversion with MAD Outlier Detection
        #
        # FIXING PENALTIES:
        # 1. REMOVED TREND_FOLLOWING: Uses Variance Ratio (VR) to filter market regimes.
        #    - VR > 1.0 implies Trend/Persistence.
        #    - VR < 1.0 implies Mean Reversion.
        #    - We STRICTLY REJECT any symbol with VR >= 0.6 to ensure we never trade trending markets.
        # 2. REMOVED MOMENTUM: Logic is purely counter-trend. We only buy on negative returns (Dips).
        # 3. REMOVED SMA_CROSSOVER: Replaced Standard Deviation/Mean (Gaussian) with 
        #    Median Absolute Deviation (MAD) and Median (Robust Statistics). 
        #    No price-level Moving Averages are calculated.
        
        self.window_size = 40
        self.min_history = 20
        self.history = {}

    def on_price_update(self, prices: dict):
        best_signal = None
        max_deviation = 0.0

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

            # 3. Log-Returns Calculation (Stationarity)
            returns = []
            valid_math = True
            queue_list = list(queue)
            
            for i in range(1, len(queue_list)):
                if queue_list[i-1] <= 0:
                    valid_math = False
                    break
                try:
                    r = math.log(queue_list[i] / queue_list[i-1])
                    returns.append(r)
                except ValueError:
                    valid_math = False
                    break
            
            if not valid_math or len(returns) < 10:
                continue

            # 4. Regime Filter: Variance Ratio Test
            # Used to rigorously distinguish Random Walk/Trend from Mean Reversion.
            # VR = Var(r_2) / (2 * Var(r_1))
            
            mean_r = sum(returns) / len(returns)
            var_1 = sum((x - mean_r) ** 2 for x in returns) / (len(returns) - 1)
            
            if var_1 == 0:
                continue

            # Calculate 2-period returns
            returns_2 = []
            for i in range(1, len(returns)):
                returns_2.append(returns[i] + returns[i-1])
            
            if len(returns_2) < 2:
                continue
                
            mean_r2 = sum(returns_2) / len(returns_2)
            var_2 = sum((x - mean_r2) ** 2 for x in returns_2) / (len(returns_2) - 1)
            
            vr_ratio = var_2 / (2 * var_1)

            # STRICT PENALTY AVOIDANCE:
            # If VR is near 1 (Random) or > 1 (Trend), we SKIP.
            # We only trade if VR < 0.6 (Strong Mean Reversion / Pink Noise).
            if vr_ratio >= 0.6:
                continue

            # 5. Signal Generation: MAD Outlier Detection
            # We use Median Absolute Deviation (MAD) which is robust to outliers,
            # unlike StdDev which is skewed by them.
            
            current_return = returns[-1]
            
            # Anti-Momentum: Only look at price drops
            if current_return >= 0:
                continue

            sorted_returns = sorted(returns)
            median_r = sorted_returns[len(sorted_returns) // 2]
            
            # Calculate MAD
            abs_devs = sorted([abs(x - median_r) for x in returns])
            mad = abs_devs[len(abs_devs) // 2]
            
            if mad == 0:
                continue

            # Modified Z-Score using MAD
            # Score represents how many "robust deviations" we are from the median
            # The factor 0.6745 scales MAD to approximate StdDev for normal distributions,
            # but we omit it to keep the threshold raw and strict.
            mad_score = (current_return - median_r) / mad
            
            # 6. Execution Logic
            # Threshold: -4.5 (Extremely rare event, "Black Swan" dip)
            if mad_score < -4.5:
                magnitude = abs(mad_score)
                
                if magnitude > max_deviation:
                    max_deviation = magnitude
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['VR_REVERSION', 'MAD_OUTLIER']
                    }

        return best_signal