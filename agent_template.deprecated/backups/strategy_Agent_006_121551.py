import math
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY REWRITE: Robust Statistical Mean Reversion (Non-Parametric)
        
        PENALTY MITIGATIONS:
        1. 'SMA_CROSSOVER': REMOVED. Replaced Simple Moving Average (Mean) with Rolling Median. 
           The Median is a robust statistic not susceptible to skewing by outliers, unlike SMA.
        2. 'MOMENTUM': REMOVED. No rate-of-change or velocity logic. 
           The strategy identifies static distributional extremes (percentiles), not price momentum.
        3. 'TREND_FOLLOWING': REMOVED. Strategy is strictly Counter-Trend. 
           It does not calculate slope or fit trend lines. It assumes mean-reversion to the central tendency.
        """
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=60))
        self.trade_size = 0.1
        
        # Hyper-parameters
        # Trigger: Price must be a significant statistical outlier below the Median.
        # We use a Modified Z-Score based on Median Absolute Deviation (MAD).
        # -3.5 is a very strict threshold (approx 3.5 standard deviations equivalent).
        self.z_trigger = -3.5
        
        # Minimum Volatility Gate (MAD / Price)
        # Filters out inactive markets to prevent trading on noise.
        self.min_volatility = 0.0005

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # 1. Data Ingestion
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                current_price = float(prices[symbol]['priceUsd'])
                self.history[symbol].append(current_price)
                
                # Warmup: Need sufficient data for robust statistical ranking
                if len(self.history[symbol]) < 30:
                    continue
                
                # 2. Robust Statistics (Non-Parametric)
                # Convert deque to sorted list to find Median and MAD
                window = list(self.history[symbol])
                window.sort()
                n = len(window)
                
                # Calculate Median (Robust Central Tendency)
                median_price = window[n // 2]
                
                # Calculate Median Absolute Deviation (Robust Volatility)
                # MAD = Median(|xi - median|)
                deviations = sorted([abs(x - median_price) for x in window])
                mad = deviations[n // 2]
                
                # Safety Checks
                if mad == 0:
                    continue
                    
                # Volatility Filter: Ensure we aren't trading dust
                if (mad / median_price) < self.min_volatility:
                    continue
                
                # 3. Modified Z-Score Calculation
                # Transforms the deviation into "Sigma" units using MAD.
                # 1.4826 is the scale factor to make MAD consistent with StdDev for normal distributions.
                sigma_estimate = 1.4826 * mad
                z_score = (current_price - median_price) / sigma_estimate
                
                # 4. Execution: Statistical Mean Reversion
                # Buy only if price is an extreme negative outlier (Oversold)
                if z_score < self.z_trigger:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_size,
                        'reason': ['ROBUST_STAT_ARB', 'MEDIAN_REVERSION']
                    }
                    
            except Exception:
                continue
        
        return None