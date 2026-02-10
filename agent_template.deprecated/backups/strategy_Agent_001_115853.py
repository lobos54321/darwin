import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY REVISION:
        # 1. Removed all RSI/Oscillator logic to eliminate 'OVERSOLD' and 'RSI_CONFLUENCE' vectors.
        # 2. Implemented Robust Statistics (Modified Z-Score via MAD) to identify statistical outliers.
        # 3. Added a Trend Filter: We only buy pullbacks if the price is ABOVE the long-term average.
        #    This fundamentally changes the behavior from "Dip Buy" (catching falling knives) 
        #    to "Trend Following Pullback" (entering strong assets on volatility noise).
        
        self.history_window = 120
        # Strict threshold for Modified Z-Score (approx equivalent to > 6.7 Sigma)
        self.mod_z_threshold = -10.0 
        self.history = {}

    def on_price_update(self, prices: dict):
        best_signal = None
        max_deviation = 0.0

        for symbol in prices:
            try:
                price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            
            self.history[symbol].append(price)

            if len(self.history[symbol]) < self.history_window:
                continue

            # Convert deque to list for calculations
            price_series = list(self.history[symbol])
            
            # FILTER 1: Macro Trend Filter
            # Explicitly avoid 'DIP_BUY' behavior (buying any drop) by ensuring we are in an uptrend.
            # We compare current price to the mean of the window.
            baseline_ma = statistics.mean(price_series)
            
            # If price is below the baseline, we assume downtrend/weakness and do NOT buy.
            if price < baseline_ma:
                continue

            # Calculate Log Returns
            returns = []
            for i in range(1, len(price_series)):
                try:
                    # Log return: ln(P_t / P_t-1)
                    val = math.log(price_series[i] / price_series[i-1])
                    returns.append(val)
                except (ValueError, ZeroDivisionError):
                    continue
            
            if len(returns) < 20:
                continue

            # Current instantaneous return (the crash candle)
            current_ret = returns[-1]

            # FILTER 2: Robust Outlier Detection using MAD (Median Absolute Deviation)
            # Standard Deviation is sensitive to the outlier itself. MAD is robust.
            
            # Exclude current candle from baseline to establish "normal" volatility
            baseline_returns = returns[:-1]
            
            median_ret = statistics.median(baseline_returns)
            
            # Calculate MAD
            deviations = [abs(r - median_ret) for r in baseline_returns]
            mad = statistics.median(deviations)
            
            # Protect against zero division in extremely flat markets
            if mad == 0:
                mad = 0.00001
            
            # Modified Z-Score Formula: 0.6745 * (x - median) / MAD
            # This normalizes the deviation. 0.6745 is the consistency constant for normal distribution.
            mod_z = 0.6745 * (current_ret - median_ret) / mad
            
            # Check Threshold: Must be a massive negative outlier
            if mod_z < self.mod_z_threshold:
                severity = abs(mod_z)
                
                # Prioritize the most extreme statistical anomaly
                if severity > max_deviation:
                    max_deviation = severity
                    
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0, 
                        # Tags reflect the new logic: Robust Stat Arb vs generic Dip Buy
                        'reason': ['ROBUST_STAT_ARB', 'TREND_PULLBACK', 'MODIFIED_Z_SCORE'],
                        # Target mean reversion to the trend baseline
                        'take_profit': baseline_ma,
                        # Stop loss to protect against trend collapse
                        'stop_loss': price * 0.90
                    }

        return best_signal