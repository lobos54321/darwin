import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Instantaneous Liquidity Shock Detector (Return-Based)
        #
        # CORRECTIONS APPLIED:
        # 1. FIXED SMA_CROSSOVER: Replaced price-level Moving Averages with Return Volatility (RMS).
        #    We now analyze the statistical distribution of price *changes* (velocity), not price levels.
        # 2. FIXED MOMENTUM: Logic is strictly anti-momentum. It buys only on severe negative 
        #    velocity (instantaneous crashes) well beyond standard volatility.
        # 3. FIXED TREND_FOLLOWING: By assuming a mean return of 0 (Random Walk), the model 
        #    penalizes sustained trends (which inflate volatility) and targets pure mean-reverting noise.
        
        self.window_size = 30
        self.z_threshold = -3.5  # Stricter Entry: Requires a 3.5 Sigma event (Liquidity Void)
        self.history = {}

    def on_price_update(self, prices: dict):
        best_signal = None
        lowest_z = 0.0

        for symbol in prices:
            # 1. Safe Price Parsing
            try:
                data = prices[symbol]
                # Handle both simple dict {symbol: price} and nested {symbol: {'priceUsd': ...}}
                price = float(data.get("priceUsd", 0) if isinstance(data, dict) else data)
                if price <= 1e-8:
                    continue
            except (ValueError, TypeError, KeyError):
                continue

            # 2. Manage History (Rolling Window of Prices)
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            queue = self.history[symbol]
            queue.append(price)

            # Need sufficient data to compute return volatility
            if len(queue) < 10:
                continue

            # 3. Calculate Returns (Instantaneous Velocity)
            # R_t = (P_t - P_t-1) / P_t-1
            returns = []
            for i in range(1, len(queue)):
                r = (queue[i] - queue[i-1]) / queue[i-1]
                returns.append(r)
            
            if not returns:
                continue

            # 4. Compute Volatility (RMS of Returns)
            # We use Root Mean Square relative to 0. This assumes the 'fair' instantaneous return 
            # is 0 (stationarity). This is stricter than standard deviation around a moving mean,
            # as it prevents buying into strong downtrends where the mean is shifting.
            sum_sq = sum(r * r for r in returns)
            volatility = math.sqrt(sum_sq / len(returns))

            if volatility <= 1e-9:
                continue

            # 5. Calculate Z-Score of the Current Return
            current_return = returns[-1]
            z_score = current_return / volatility

            # 6. Signal Generation: Liquidity Shock
            if z_score < self.z_threshold:
                # Prioritize the most extreme statistical outlier
                if z_score < lowest_z:
                    lowest_z = z_score
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['LIQUIDITY_SHOCK', 'RETURN_ANOMALY', 'PURE_MEAN_REVERSION']
                    }

        return best_signal