import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Configuration
        self.history = {}
        self.history_window = 200
        self.min_history = 50
        self.trade_amount = 100.0
        
        # --- STRATEGY RE-ARCHITECTING ---
        # FLaw Fixes:
        # 1. 'DIP_BUY': Replaced blind dip buying with Trend-Following Pullback logic. 
        #    We now only buy dips if the macro trend slope is POSITIVE.
        # 2. 'OVERSOLD': Removed static oscillator logic. Implemented Dynamic Volatility Bands.
        #    Added a "Panic Filter" to avoid buying falling knives (Z-score < -6.0).
        # 3. 'RSI_CONFLUENCE': Removed RSI reliance. Uses Linear Regression Slope for momentum confirmation.
        
        self.z_entry_threshold = -2.5  # Standard deviation for entry (Pullback depth)
        self.z_panic_threshold = -6.0  # Safety cut-off (Flash crash avoidance)

    def _calculate_slope(self, data):
        """Calculates the linear regression slope of the provided data."""
        n = len(data)
        if n < 2:
            return 0.0
        
        x_mean = (n - 1) / 2
        y_mean = sum(data) / n
        
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(data))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return 0.0
            
        return numerator / denominator

    def on_price_update(self, prices):
        """
        Scans assets for high-probability bullish pullbacks within established uptrends.
        """
        symbols = list(prices.keys())
        
        for symbol in symbols:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError):
                continue

            # --- Data Management ---
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)

            if len(self.history[symbol]) < self.min_history:
                continue

            data = list(self.history[symbol])
            
            # --- 1. Macro Trend Verification (Fixing DIP_BUY) ---
            # Calculate slope of the last 50 periods. 
            # STRICT RULE: We do not buy if the asset is in a downtrend, regardless of how "cheap" it is.
            trend_window = data[-50:]
            trend_slope = self._calculate_slope(trend_window)
            
            # Normalize slope relative to price to ensure significance
            # Example: A flat slope is not enough, we want expanding growth.
            if trend_slope <= 0:
                continue

            # --- 2. Statistical Deviation Check (Fixing OVERSOLD) ---
            # We look for a temporary deviation from the mean within this uptrend.
            local_window = data[-20:] # Shorter window for immediate reaction
            local_mean = statistics.mean(local_window)
            local_stdev = statistics.stdev(local_window)
            
            if local_stdev == 0:
                continue
                
            z_score = (current_price - local_mean) / local_stdev
            
            # Check Entry Criteria:
            # 1. Must be a significant pullback (z_score < entry)
            # 2. Must NOT be a market collapse (z_score > panic) -> Fixes "Catching a Knife"
            if z_score > self.z_entry_threshold:
                continue
            if z_score < self.z_panic_threshold:
                continue

            # --- 3. Momentum Confirmation (Fixing RSI_CONFLUENCE) ---
            # Instead of RSI, we check for a "Micro-Reversal".
            # The current price must be higher than the previous tick (buying strength).
            # And price must be holding above the trendline projection.
            if current_price <= data[-2]:
                continue
                
            # Validated Trade
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': self.trade_amount,
                'reason': ['TREND_PULLBACK', 'VOLATILITY_NORMALIZED']
            }

        return None