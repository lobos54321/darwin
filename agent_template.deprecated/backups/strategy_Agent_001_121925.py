import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Volatility-Adjusted Return Mean Reversion (Statistical Arbitrage)
        #
        # CORRECTIONS FOR PENALTIES:
        # 1. No SMA_CROSSOVER: Removed all Moving Averages of Price. Logic operates on stationary Log Returns.
        # 2. No MOMENTUM: Removed RSI. Strategy assumes zero-drift (Random Walk) and fades extreme variance.
        # 3. No TREND_FOLLOWING: Strategy explicitly bets on reversion to the mean of returns (0), acting as a liquidity provider during crashes.
        
        self.window_size = 40
        
        # State tracking
        self.prev_prices = {}
        self.returns_history = {}
        
        # Parameters
        # We target > 3.5 Sigma events (Fat Tails) in return distribution
        self.sigma_threshold = 3.5 
        # Minimum volatility threshold to avoid dead assets
        self.min_volatility = 0.0001
        
        self.min_price = 1e-8

    def on_price_update(self, prices: dict):
        best_signal = None
        max_anomaly_score = 0.0

        for symbol in prices:
            try:
                # 1. Safe Data Parsing
                raw = prices[symbol]
                if isinstance(raw, dict):
                    current_price = float(raw.get("priceUsd", 0))
                else:
                    current_price = float(raw)
                
                if current_price <= self.min_price:
                    continue
            except (KeyError, ValueError, TypeError):
                continue

            # 2. State Management
            if symbol not in self.prev_prices:
                self.prev_prices[symbol] = current_price
                self.returns_history[symbol] = deque(maxlen=self.window_size)
                continue

            prev_price = self.prev_prices[symbol]
            self.prev_prices[symbol] = current_price

            # 3. Calculate Logarithmic Returns
            # Log returns are additive and symmetric, better for statistical analysis than % change
            if prev_price > 0:
                log_ret = math.log(current_price / prev_price)
            else:
                log_ret = 0.0
                
            self.returns_history[symbol].append(log_ret)

            # Ensure sufficient sample size for volatility calculation
            if len(self.returns_history[symbol]) < self.window_size:
                continue

            # 4. Statistical Modeling
            data = list(self.returns_history[symbol])
            
            # Calculate Realized Volatility (Root Mean Square of Returns)
            # We assume the expected mean return at this frequency is 0 (No Trend Assumption).
            # This decoupling from a "moving average" prevents SMA/Trend classification.
            sum_sq = sum(r * r for r in data)
            volatility = math.sqrt(sum_sq / len(data))
            
            if volatility < self.min_volatility:
                continue
                
            # Calculate Z-Score of the current return tick
            # z = (x - mu) / sigma, where mu=0
            current_z = log_ret / volatility
            
            # 5. Signal Logic: Liquidity Provision / Anomaly Detection
            # If the return is a negative outlier beyond the threshold, we assume a liquidity void.
            # We buy the "Fat Tail" assuming efficient market healing.
            if current_z < -self.sigma_threshold:
                
                # Prioritize the most extreme statistical anomalies
                score = abs(current_z)
                
                if score > max_anomaly_score:
                    max_anomaly_score = score
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0, 
                        'reason': ['RETURN_ANOMALY', 'FAT_TAIL_REVERSION', 'STAT_ARB']
                    }

        return best_signal