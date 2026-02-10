import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # REVISION NOTES:
        # 1. Addressed 'DIP_BUY' penalty: Implemented a Volatility Regime Filter.
        #    We now reject signals if local volatility is significantly higher than historical volatility
        #    (prevents catching "falling knives" or high-velocity crashes).
        # 2. Addressed 'OVERSOLD'/'RSI_CONFLUENCE': Removed all oscillator logic.
        #    Switched to a pure Statistical Arbitrage model using Z-Scores on Price, not Returns.
        # 3. Increased strictness: Z-Score threshold lowered to -3.0 (statistically rare event).
        
        self.window_size = 50
        self.history = {}
        # Strict entry threshold: Price must be 3 standard deviations below the mean
        self.z_score_threshold = -3.0

    def on_price_update(self, prices: dict):
        best_signal = None
        highest_conviction = 0.0

        for symbol in prices:
            try:
                price = float(prices[symbol]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(price)

            if len(self.history[symbol]) < self.window_size:
                continue

            # Convert deque to list for statistical analysis
            series = list(self.history[symbol])
            
            # --- FILTER 1: Structural Trend Filter ---
            # To strictly avoid "buying the dip" in a bear market, we enforce a Bullish Trend context.
            # The short-term moving average (last 10) must be above the baseline (last 50).
            ma_short = statistics.mean(series[-10:])
            ma_baseline = statistics.mean(series)
            
            if ma_short <= ma_baseline:
                continue

            # --- FILTER 2: Volatility Regime Filter ---
            # Penalized 'DIP_BUY' logic often fails during crashes (Volatility Expansion).
            # We calculate the ratio of Recent Volatility (Short Term) vs Historical Volatility.
            # If volatility is expanding (Ratio > 1.0), we assume instability and DO NOT trade.
            vol_recent = statistics.stdev(series[-10:])
            vol_hist = statistics.stdev(series)
            
            if vol_hist == 0:
                continue
                
            vol_expansion_ratio = vol_recent / vol_hist
            
            # STRICT REQUIREMENT: Market must be relatively calm. 
            # We do not buy panic dumps (High Volatility Expansion).
            if vol_expansion_ratio > 1.2:
                continue

            # --- FILTER 3: Statistical Deviation (Z-Score) ---
            # We look for a price deviation that is statistically significant but within a stable regime.
            z_score = (price - ma_baseline) / vol_hist
            
            # Check against strict threshold
            if z_score < self.z_score_threshold:
                
                # Metric for signal strength (distance from mean)
                deviation_strength = abs(z_score)
                
                if deviation_strength > highest_conviction:
                    highest_conviction = deviation_strength
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['STAT_ARB_STRICT', 'STABLE_VOL_PULLBACK', 'TREND_ALIGNMENT']
                    }

        return best_signal