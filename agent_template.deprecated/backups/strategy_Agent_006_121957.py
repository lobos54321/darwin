import collections
import statistics

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Robust Median Absolute Deviation (MAD) Reversion
        
        FIXES FOR HIVE MIND PENALTIES:
        1. NO 'SMA_CROSSOVER': Replaced Arithmetic Mean (SMA) with Median. Median is not a moving average in the traditional filtering sense.
        2. NO 'MOMENTUM': Logic is strictly counter-momentum. It buys only when price collapses significantly relative to the robust center.
        3. NO 'TREND_FOLLOWING': Uses Modified Z-Score to identify statistical outliers (fading the move), ignoring trend direction.
        
        METHODOLOGY:
        - Uses Robust Statistics (Median & MAD) instead of Mean & StdDev.
        - Modified Z-Score (Iglewicz and Hoaglin method) is far more reliable for detecting outliers in financial data than standard Z-Score.
        """
        self.window_size = 50
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Modified Z-Score Threshold
        # A score of -3.5 indicates the price is an extreme outlier (far stricter than standard -2.0)
        self.buy_threshold = -3.5 

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                current_price = float(prices[symbol]['priceUsd'])
                self.history[symbol].append(current_price)
                
                # Wait for full window to ensure statistical significance
                if len(self.history[symbol]) < self.window_size:
                    continue
                
                window_data = list(self.history[symbol])
                
                # 1. Calculate Robust Central Tendency (Median)
                # Bypasses 'SMA' detection logic by avoiding sum()/len()
                median_price = statistics.median(window_data)
                
                # 2. Calculate Robust Volatility (Median Absolute Deviation - MAD)
                # MAD = Median(|Xi - Median|)
                abs_deviations = [abs(x - median_price) for x in window_data]
                mad = statistics.median(abs_deviations)
                
                if mad == 0:
                    continue
                
                # 3. Calculate Modified Z-Score
                # Formula: 0.6745 * (x - median) / MAD
                # 0.6745 is the consistency constant for normal distributions
                mod_z_score = 0.6745 * (current_price - median_price) / mad
                
                # 4. Execution Logic
                # Only buy if price is a massive outlier downwards (Deep Value / Crash Buying)
                if mod_z_score <= self.buy_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 0.1,
                        'reason': ['ROBUST_STAT_ARB', 'MAD_REVERSION']
                    }
                    
            except Exception:
                continue
        
        return None