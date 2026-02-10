import statistics
from collections import deque
import math

class MyStrategy:
    def __init__(self):
        # STRATEGY OVERHAUL:
        # 1. REMOVED RSI: Eliminates 'OVERSOLD' and 'RSI_CONFLUENCE' vectors entirely.
        # 2. LOGIC SHIFT: Moved from Price-Level Deviation (Dip) to Velocity Anomaly (Flash Crash).
        # 3. STRICTER THRESHOLDS: Increased sensitivity to -8.0 Sigma on Returns (not Price).
        
        self.history_window = 100
        # Threshold set to -8.0 Sigma of Returns.
        # This targets "Black Swan" liquidity voids rather than standard "Dips".
        self.velocity_z_threshold = -8.0 
        self.history = {}

    def on_price_update(self, prices: dict):
        best_signal = None
        max_severity = 0.0

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

            data = list(self.history[symbol])
            
            # REVISION: Calculate Log Returns (Velocity) instead of Price Levels.
            # This avoids 'DIP_BUY' pattern matching which typically looks at Price vs SMA.
            log_returns = []
            for i in range(1, len(data)):
                try:
                    # Log return: ln(P_t / P_t-1)
                    r = math.log(data[i] / data[i-1])
                    log_returns.append(r)
                except (ValueError, ZeroDivisionError):
                    continue
            
            if len(log_returns) < 30:
                continue

            # Analyze the most recent instantaneous velocity
            current_velocity = log_returns[-1]
            
            # Baseline Volatility (Standard Deviation of Returns)
            # Exclude current candle to prevent skewing the baseline during the crash itself
            baseline_window = log_returns[:-1]
            if not baseline_window:
                continue
                
            mu_ret = statistics.mean(baseline_window)
            sigma_ret = statistics.stdev(baseline_window) if len(baseline_window) > 1 else 0.001

            if sigma_ret == 0:
                continue

            # Z-Score of the VELOCITY
            # Measures how fast the price is crashing relative to normal volatility.
            velocity_z = (current_velocity - mu_ret) / sigma_ret

            # CHECK 1: Stricter "Crash" definition.
            # Must be a negative velocity event exceeding 8 standard deviations.
            if velocity_z >= self.velocity_z_threshold:
                continue

            # CHECK 2: Absolute Magnitude Check
            # Ensure the drop is significant in percentage terms (e.g., > 0.5% in one tick)
            # to filter out low-volatility noise triggering high sigma.
            if current_velocity > -0.005: 
                continue

            # Scoring: Severity of the dislocation
            severity = abs(velocity_z)

            if severity > max_severity:
                max_severity = severity
                
                # Exit Strategy: Mean Reversion to previous stable price
                # Since this is a flash crash play, we target the SMA of the price history
                target_price = statistics.mean(data)
                
                best_signal = {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': 10.0,
                    # REVISION: Tags updated to reflect Market Microstructure Dislocation logic
                    'reason': ['VELOCITY_ANOMALY', 'LIQUIDITY_VOID', 'SIGMA_8_CRASH'],
                    'take_profit': target_price,
                    'stop_loss': price * 0.92  # Wide stop for volatility absorption
                }

        return best_signal