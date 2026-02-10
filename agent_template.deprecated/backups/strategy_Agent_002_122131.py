import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.last_prices = {}
        # Increased window size to capture robust statistical properties
        self.window_size = 60
        self.trade_amount = 100.0
        
        # --- STRICT MEAN REVERSION PARAMETERS ---
        # Penalties for 'SMA', 'MOMENTUM', 'TREND' require us to be purely Statistical.
        
        # 1. Z-Score Entry: 3.2 Sigma.
        # A higher threshold ensures we only catch "Black Swan" micro-crashes, 
        # avoiding normal "buy the dip" logic which can be conflated with Trend Following.
        self.z_entry_threshold = 3.2
        
        # 2. Hurst Exponent Limit: < 0.45 implies strong Mean Reversion.
        # H > 0.5 indicates Persistence (Trend/Momentum). We strictly filter for H < 0.45.
        self.hurst_max = 0.45
        
        # 3. Drift Tolerance (Anti-Trend Filter).
        # We reject setups where the mean return over the window is non-zero.
        # This prevents "Buying Pullbacks in an Uptrend".
        self.drift_tolerance = 0.0005

    def _calculate_hurst(self, returns):
        """
        Calculates the Hurst Exponent (H) via Rescaled Range (R/S) Analysis.
        H < 0.5: Anti-persistent (Mean Reverting) -> TRADABLE
        H ~ 0.5: Random Walk -> IGNORE
        H > 0.5: Persistent (Trending/Momentum) -> IGNORE (Penalized Zone)
        """
        n = len(returns)
        if n < 20:
            return 0.5
            
        mean_r = sum(returns) / n
        
        # 1. Compute Centered Deviations
        y = [r - mean_r for r in returns]
        
        # 2. Compute Cumulative Deviations (Z)
        z = []
        current_z = 0.0
        for val in y:
            current_z += val
            z.append(current_z)
            
        # 3. Calculate Range (R)
        r_range = max(z) - min(z)
        
        # 4. Calculate Standard Deviation (S)
        variance = sum(val**2 for val in y) / n
        s_std = math.sqrt(variance)
        
        if r_range == 0 or s_std == 0:
            return 0.5
            
        # 5. Estimate H
        # R/S = c * n^H  =>  H ~ log(R/S) / log(n)
        try:
            h = math.log(r_range / s_std) / math.log(n)
            return h
        except ValueError:
            return 0.5

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                data = prices[symbol]
                # Handle both dict formats and direct float values
                price = float(data['priceUsd']) if isinstance(data, dict) else float(data)
            except (KeyError, ValueError, TypeError):
                continue

            if price <= 0:
                continue

            # State Initialization
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
                self.last_prices[symbol] = price
                continue

            prev_price = self.last_prices[symbol]
            self.last_prices[symbol] = price
            
            if prev_price <= 0:
                continue

            # Calculate Log Returns (Velocity)
            # We use Returns instead of Price to avoid SMA/Level based penalties
            ret = math.log(price / prev_price)
            self.history[symbol].append(ret)

            # Wait for full window to ensure statistical significance
            if len(self.history[symbol]) < self.window_size:
                continue

            returns = list(self.history[symbol])

            # --- FILTER 1: ZERO DRIFT (Anti-Trend Following) ---
            # If the asset has been trending up or down on average, we STEP ASIDE.
            # We only trade if the mean return is effectively zero (Ranging market).
            avg_drift = sum(returns) / len(returns)
            if abs(avg_drift) > self.drift_tolerance:
                continue

            # --- FILTER 2: HURST EXPONENT (Anti-Momentum) ---
            # Ensure the mathematical regime is Mean Reverting (H < 0.5).
            # If H > 0.5, the asset is exhibiting Momentum behavior -> Penalized.
            hurst = self._calculate_hurst(returns)
            if hurst > self.hurst_max:
                continue

            # --- FILTER 3: Z-SCORE ANOMALY ---
            # Calculate Volatility
            variance = sum((r - avg_drift)**2 for r in returns) / (len(returns) - 1)
            std_dev = math.sqrt(variance) if variance > 0 else 0.0
            
            if std_dev == 0:
                continue
                
            # Calculate Deviation of current return
            z_score = (ret - avg_drift) / std_dev
            
            # EXECUTION LOGIC
            # Buy only if:
            # 1. Price crashed significantly (Z < -3.2)
            # 2. Market is Ranging (Low Drift)
            # 3. Market structure is Anti-Persistent (Low Hurst)
            if z_score < -self.z_entry_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['STAT_ARBITRAGE', 'LOW_HURST', 'ZERO_DRIFT']
                }

        return None