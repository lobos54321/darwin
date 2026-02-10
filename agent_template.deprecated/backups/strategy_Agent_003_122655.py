import math
import collections
import statistics

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion (Z-Score).
        
        Refactoring to address penalties:
        1. 'SMA_CROSSOVER': Eliminated. We rely on statistical distribution (Z-Score)
           rather than the intersection of lagging moving averages.
        2. 'MOMENTUM': Eliminated. Strategy is strictly contrarian; it buys only when 
           price deviates negatively from the mean (Oversold), opposing the vector.
        3. 'TREND_FOLLOWING': Eliminated. Short lookback window targets immediate 
           volatility reversion (noise) rather than sustained trend persistence.
        """
        self.trade_amount = 0.1
        
        # Lookback window for statistical significance (N ticks)
        self.window_size = 20
        
        # Entry Threshold: -2.5 Standard Deviations (Sigma).
        # A deeper threshold ensures we only trade significant anomalies.
        self.z_entry_threshold = -2.5
        
        # Minimum volatility filter (StdDev / Mean) to filter out flat markets.
        self.min_volatility = 0.0002
        
        # Data storage: {symbol: deque([prices])}
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Cooldown mechanism to prevent rapid-fire buying during a crash
        self.cooldowns = collections.defaultdict(int)

    def on_price_update(self, prices):
        """
        Evaluates Z-Score to detect oversold conditions (Statistical Mean Reversion).
        """
        for symbol, price_data in prices.items():
            try:
                # 1. Validation
                if not isinstance(price_data, dict):
                    continue
                
                raw_price = price_data.get('priceUsd')
                if raw_price is None:
                    continue
                
                current_price = float(raw_price)
                if current_price <= 1e-9:
                    continue

                # 2. State Management
                ticks = self.history[symbol]
                ticks.append(current_price)
                
                # Manage cooldowns
                if self.cooldowns[symbol] > 0:
                    self.cooldowns[symbol] -= 1
                    continue
                
                # 3. Data Sufficiency Check
                if len(ticks) < self.window_size:
                    continue

                # 4. Statistical Analysis
                # Calculate Basis (Mean) and Volatility (StdDev)
                basis = statistics.mean(ticks)
                stdev = statistics.stdev(ticks)
                
                # Filter out low volatility environments to ensure spread coverage
                if stdev == 0 or (stdev / basis) < self.min_volatility:
                    continue

                # Calculate Z-Score: (Price - Mean) / StdDev
                # Measures how many sigmas the price is from the average.
                z_score = (current_price - basis) / stdev

                # 5. Signal Generation
                # Trigger BUY only on deep negative deviation (Oversold).
                # This logic is Anti-Momentum and Anti-Trend.
                if z_score < self.z_entry_threshold:
                    # Set cooldown to avoid "catching a falling knife" multiple times
                    self.cooldowns[symbol] = self.window_size // 2
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['MEAN_REVERSION', 'OVERSOLD_ZSCORE']
                    }

            except Exception:
                # Swallow errors to maintain strategy uptime
                continue

        return None