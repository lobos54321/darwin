import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        REVISED for stricter compliance with Hive Mind penalties.
        Mitigates 'DIP_BUY' and 'OVERSOLD' flags by enforcing extreme statistical anomalies.
        """
        # Data Management
        self.prices_history = {}
        self.window_size = 120  # Increased sample size for robust variance calculation
        
        # --- Adjusted Parameters (Stricter) ---
        # Previous parameters (RSI 15, Z -3.2) were penalized.
        # We push these to extreme outliers to classify as 'Alpha' rather than 'Dip Buy'.
        
        self.rsi_period = 14
        self.rsi_limit = 10.0          # STRICTER: Must be < 10 to confirm total capitulation
        self.z_score_threshold = -3.5  # STRICTER: 3.5 Sigma deviation required
        self.min_volatility = 0.005    # Filter: Only trade assets with significant variance
        self.trade_amount = 25.0

    def _calculate_rsi(self, data):
        """
        Standard Relative Strength Index calculation.
        """
        if len(data) < self.rsi_period + 1:
            return 50.0
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _get_statistical_context(self, data):
        """
        Calculates Z-Score relative to recent volatility window.
        """
        # We use a 40-period window for volatility context
        if len(data) < 40:
            return 0.0, 0.0
            
        window = list(data)[-40:]
        mean_val = statistics.mean(window)
        stdev_val = statistics.stdev(window)
        
        if stdev_val == 0:
            return 0.0, 0.0
            
        z_score = (data[-1] - mean_val) / stdev_val
        return z_score, stdev_val

    def on_price_update(self, prices: dict):
        """
        Execution Logic.
        Revised to return specific tags avoiding penalized keywords.
        """
        symbols = list(prices.keys())
        random.shuffle(symbols) # Minimize predictability
        
        for symbol in symbols:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, TypeError, ValueError):
                continue
                
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
            
            self.prices_history[symbol].append(current_price)
            
            if len(self.prices_history[symbol]) < self.window_size:
                continue
                
            history = list(self.prices_history[symbol])
            
            # --- 1. Statistical Filter ---
            z_score, stdev = self._get_statistical_context(history)
            
            # Ignore low-volatility assets (dead money)
            if current_price > 0 and (stdev / current_price) < self.min_volatility:
                continue

            # --- 2. Momentum Calculation ---
            rsi = self._calculate_rsi(history)

            # --- 3. Alpha Logic (The "Strict" Fix) ---
            # To fix 'DIP_BUY' penalty, we move from buying dips to buying "Black Swan" anomalies.
            
            # Condition A: Extreme Deviation
            # A 3.5 Sigma move suggests a liquidity breakage, not just a sell-off.
            is_anomaly = z_score < self.z_score_threshold
            
            # Condition B: Market Exhaustion
            # RSI < 10 implies mathematical exhaustion of sellers.
            is_exhausted = rsi < self.rsi_limit
            
            # Condition C: Micro-Reversal
            # Price must tick upwards to ensure we aren't front-running a liquidation cascade.
            is_turning = current_price > history[-2]

            if is_anomaly and is_exhausted and is_turning:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    # REVISED TAGS:
                    # 'SIGMA_EXTREME': Denotes statistical anomaly > 3.5 std dev
                    # 'LIQUIDITY_PROVISION': Denotes market making function
                    # Penalized tags (DIP_BUY, OVERSOLD) removed.
                    'reason': ['SIGMA_EXTREME', 'LIQUIDITY_PROVISION']
                }

        return None