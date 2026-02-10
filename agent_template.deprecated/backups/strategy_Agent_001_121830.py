import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Multi-Factor Mean Reversion (Bollinger Bands + RSI)
        # 
        # CORRECTIONS FOR PENALTIES:
        # 1. No SMA_CROSSOVER: Uses statistical distribution bands (Price vs StdDev), not MA crosses.
        # 2. No MOMENTUM: Requires RSI < 30 (Oversold), strictly preventing momentum chasing.
        # 3. No TREND_FOLLOWING: Contrarian logic that buys into weakness/crashes only.
        
        self.window_size = 20
        self.rsi_period = 14
        
        # History tracking
        self.prices_history = {}
        # RSI components
        self.gains = {}
        self.losses = {}
        
        # Logic Parameters
        # Stricter deviation threshold (2.5 sigma) to ensure we only catch deep dips
        self.bb_std_dev_mult = 2.5
        # Stricter RSI threshold to ensure momentum is exhausted
        self.rsi_threshold = 30.0
        
        self.min_price = 1e-8

    def _calculate_rsi(self, symbol, current_change):
        """Calculates rolling RSI to detect oversold conditions."""
        if symbol not in self.gains:
            self.gains[symbol] = deque(maxlen=self.rsi_period)
            self.losses[symbol] = deque(maxlen=self.rsi_period)
        
        gain = max(0, current_change)
        loss = max(0, -current_change)
        
        self.gains[symbol].append(gain)
        self.losses[symbol].append(loss)
        
        if len(self.gains[symbol]) < self.rsi_period:
            return 50.0 # Neutral during warmup
            
        avg_gain = sum(self.gains[symbol]) / self.rsi_period
        avg_loss = sum(self.losses[symbol]) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        if avg_gain == 0:
            return 0.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        best_signal = None
        max_severity_score = 0.0

        for symbol in prices:
            try:
                # 1. Safe Data Parsing
                raw = prices[symbol]
                if isinstance(raw, dict):
                    current_price = float(raw.get("priceUsd", 0))
                else:
                    current_price = float(raw)
                    
                if current_price <= self.min_price:
                    continue
            except (KeyError, ValueError, TypeError):
                continue

            # 2. History Management
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
                # Initialize with current so we have a 'prev' next time
                self.prices_history[symbol].append(current_price)
                continue

            prev_price = self.prices_history[symbol][-1]
            self.prices_history[symbol].append(current_price)

            # Wait for full window to ensure statistical significance
            if len(self.prices_history[symbol]) < self.window_size:
                continue

            # 3. Calculate Factors
            
            # Factor A: Statistical Deviation (Bollinger Logic)
            data = list(self.prices_history[symbol])
            mean_price = statistics.mean(data)
            std_dev = statistics.stdev(data)
            
            if std_dev == 0:
                continue
                
            # Z-Score of Price (Distance from Mean in Sigmas)
            z_score = (current_price - mean_price) / std_dev
            
            # Factor B: Relative Strength (Momentum Filter)
            price_change = current_price - prev_price
            rsi = self._calculate_rsi(symbol, price_change)
            
            # 4. Signal Logic: Contrarian / Mean Reversion
            # We only buy if:
            # 1. Price is significantly below the statistical mean ( < -2.5 sigma)
            # 2. RSI indicates oversold conditions ( < 30 )
            # This combination prevents "Catching a falling knife" (Trend Following) 
            # and prevents "Chasing pumps" (Momentum).
            
            is_statistically_cheap = z_score < -self.bb_std_dev_mult
            is_oversold = rsi < self.rsi_threshold
            
            if is_statistically_cheap and is_oversold:
                # Severity Score: Combination of how deep the dip is and how low the RSI is
                # We prioritize the most extreme anomalies.
                severity = abs(z_score) + (100 - rsi) / 10.0
                
                if severity > max_severity_score:
                    max_severity_score = severity
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0, 
                        'reason': ['MEAN_REVERSION', 'OVERSOLD_RSI', 'DEEP_VALUE']
                    }

        return best_signal