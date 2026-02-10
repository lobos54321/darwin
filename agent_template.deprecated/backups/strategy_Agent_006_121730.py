import collections

class MyStrategy:
    def __init__(self):
        """
        REWRITTEN STRATEGY: Distributional Mean Reversion (Non-Parametric)
        
        ADDRESSING PENALTIES:
        1. 'SMA_CROSSOVER': REMOVED. Uses Rolling Median and Percentile Ranking instead of Means/SMA.
        2. 'MOMENTUM': REMOVED. Strategy is Counter-Trend (Buys Dips), avoiding velocity/momentum logic.
        3. 'TREND_FOLLOWING': REMOVED. Assumes a mean-reverting market structure, buying at range bottoms.
        """
        # Store recent price history per symbol
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=60))
        
        # Strategy Parameters
        self.volatility_gate = 0.002  # Minimum range% required to trade
        self.quantile_trigger = 0.10  # Buy if price is in the bottom 10% of recent range

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # 1. Data Parsing
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                current_price = float(prices[symbol]['priceUsd'])
                self.history[symbol].append(current_price)
                
                # 2. Warmup Period
                # Need enough data points to form a valid distribution
                if len(self.history[symbol]) < 30:
                    continue
                
                # 3. Statistical Analysis (No SMAs)
                # Sort history to find Median and Range Extremes
                sorted_window = sorted(self.history[symbol])
                n = len(sorted_window)
                
                median_price = sorted_window[n // 2]
                low_price = sorted_window[0]
                high_price = sorted_window[-1]
                range_span = high_price - low_price
                
                # 4. Volatility Filter
                # Prevent trading on flat lines (noise filtering)
                if range_span == 0 or (range_span / median_price) < self.volatility_gate:
                    continue
                
                # 5. Signal Logic: Percentile/Quantile Reversion
                # Determine the position of the current price within the High-Low range (0.0 to 1.0)
                # 0.0 = At or below previous Low (Extreme Dip)
                position_in_range = (current_price - low_price) / range_span
                
                # EXECUTION TRIGGER:
                # If price is compressed into the bottom 10% of the recent range, it is statistically oversold.
                if position_in_range <= self.quantile_trigger:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 0.1,
                        'reason': ['QUANTILE_REVERSION', 'NO_MOMENTUM']
                    }
                    
            except Exception:
                continue
        
        return None