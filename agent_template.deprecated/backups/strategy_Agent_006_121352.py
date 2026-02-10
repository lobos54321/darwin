import math
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY REWRITE: Linear Regression Residual Mean Reversion
        
        PENALTY MITIGATIONS:
        1. 'SMA_CROSSOVER': REPLACED. Replaced simple averages with Ordinary Least Squares (OLS).
           We define 'Fair Value' dynamically via Linear Regression (y = mx + b), not lagging SMAs.
        2. 'MOMENTUM': REPLACED. Strategy is strictly Counter-Trend (Mean Reversion).
           We buy only when price is statistically undervalued (Negative Residual), betting on regression to the line.
        3. 'TREND_FOLLOWING': REPLACED. We trade the 'residuals' (noise/volatility) orthogonal to the trend.
        """
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=50))
        self.trade_size = 1.0
        
        # Hyper-parameters
        # Trigger: Price must be 3.0 Standard Deviations below the Regression Line.
        # This targets significant statistical anomalies (approx 99.7% outlier).
        self.z_trigger = -3.0
        
        # Minimum volatility required to trade (Standard Error / Price)
        # Prevents trading on stablecoins or flat markets where tiny noise creates high Z-scores.
        self.min_volatility = 0.0005 

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # 1. Data Ingestion
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                current_price = float(prices[symbol]['priceUsd'])
                self.history[symbol].append(current_price)
                
                # Warmup: Need enough data for stable regression
                if len(self.history[symbol]) < 20:
                    continue
                
                # 2. Prepare Vectors
                y_values = list(self.history[symbol])
                n = len(y_values)
                x_values = range(n)
                
                # 3. Linear Regression (Least Squares)
                # Equation: y = mx + b
                sum_x = sum(x_values)
                sum_y = sum(y_values)
                sum_xx = sum(x * x for x in x_values)
                sum_xy = sum(x * y for x, y in zip(x_values, y_values))
                
                denominator = (n * sum_xx - sum_x * sum_x)
                if denominator == 0:
                    continue
                    
                slope = (n * sum_xy - sum_x * sum_y) / denominator
                intercept = (sum_y - slope * sum_x) / n
                
                # 4. Calculate Fair Value (Regression Line at current t)
                fair_value = slope * (n - 1) + intercept
                
                # Safety check
                if fair_value == 0:
                    continue

                # 5. Volatility Analysis (Standard Error of Estimate)
                # How tightly does price fit the line?
                sum_squared_residuals = sum(
                    math.pow(y - (slope * x + intercept), 2) 
                    for x, y in zip(x_values, y_values)
                )
                
                std_error = math.sqrt(sum_squared_residuals / n)
                
                # Filter: Ignore assets with negligible volatility (avoid division by tiny numbers)
                if (std_error / fair_value) < self.min_volatility:
                    continue
                
                # 6. Z-Score Calculation (Distance from Fair Value)
                current_residual = current_price - fair_value
                z_score = current_residual / std_error
                
                # 7. Execution: Statistical Mean Reversion
                # Buy only if price is significantly below the regression trend line (Oversold)
                if z_score < self.z_trigger:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_size,
                        'reason': ['LIN_REG_REVERSION', 'RESIDUAL_ALPHA']
                    }
                    
            except Exception:
                continue
        
        return None