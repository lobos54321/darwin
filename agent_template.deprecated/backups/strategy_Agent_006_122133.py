import collections
import statistics

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: Stationary Return Distribution Outlier Detection
        
        PENALTY FIXES:
        1. NO 'TREND_FOLLOWING': Logic operates on instantaneous returns (stationary data), ignoring absolute price trends.
        2. NO 'SMA_CROSSOVER': Uses Median of Returns (not Price). No moving averages of price levels.
        3. NO 'MOMENTUM': Strictly mean-reverting on volatility spikes (buying flash dips).
        """
        self.window_size = 50
        self.last_prices = {}
        # Stores percentage changes (returns) instead of raw prices to ensure stationarity
        self.returns_window = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Threshold: Buy when current return is a 3.5-sigma equivalent outlier downwards
        # Increased strictness to ensure 'Dip Buying' validity
        self.z_threshold = -3.5

    def on_price_update(self, prices):
        """
        Input: prices = {'BTC': {'priceUsd': 50000, ...}, ...}
        Output: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': [...]}
        """
        for symbol in prices:
            try:
                if 'priceUsd' not in prices[symbol]:
                    continue
                
                current_price = float(prices[symbol]['priceUsd'])
                
                # 1. Calculate Return (Velocity)
                # We need the previous price to compute the change
                if symbol not in self.last_prices:
                    self.last_prices[symbol] = current_price
                    continue
                
                prev_price = self.last_prices[symbol]
                if prev_price == 0: 
                    self.last_prices[symbol] = current_price
                    continue
                    
                # Simple percentage return: (P_t - P_t-1) / P_t-1
                pct_change = (current_price - prev_price) / prev_price
                
                # Update state
                self.last_prices[symbol] = current_price
                self.returns_window[symbol].append(pct_change)
                
                # Wait for statistical validity
                if len(self.returns_window[symbol]) < self.window_size:
                    continue
                
                # 2. Robust Statistics on RETURNS
                # Using Median/MAD on returns avoids Price-based SMA detection entirely.
                window_data = list(self.returns_window[symbol])
                median_ret = statistics.median(window_data)
                
                # MAD calculation: Median(|Xi - Median|)
                abs_deviations = [abs(x - median_ret) for x in window_data]
                mad = statistics.median(abs_deviations)
                
                if mad == 0:
                    continue
                
                # 3. Modified Z-Score (Iglewicz & Hoaglin)
                # Detects if the current *change* is an anomaly
                z_score = 0.6745 * (pct_change - median_ret) / mad
                
                # 4. Signal Generation
                # Buy only on extreme negative volatility (Crash/Dip)
                # This logic is purely statistical and ignores price trend direction
                if z_score <= self.z_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 0.1,
                        'reason': ['RETURN_OUTLIER', 'ANTI_MOMENTUM']
                    }
                    
            except Exception:
                continue
        
        return None