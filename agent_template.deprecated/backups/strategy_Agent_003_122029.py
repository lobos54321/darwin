import collections
import math

class MyStrategy:
    def __init__(self):
        """
        Strategy: High-Frequency Statistical Mean Reversion (Counter-Trend).
        
        Architecture:
        - Replaces SMA logic with Gaussian Distribution analysis (Z-Score).
        - Counter-acts MOMENTUM and TREND_FOLLOWING by strictly buying statistical oversold extremes.
        - Uses a short volatility window to isolate price noise from macro trends.
        """
        # Reduced window size to isolate immediate volatility (Noise) vs Trend
        self.window_size = 20
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Strict Statistical Thresholds
        # Z-Score < -3.0 implies price is 3 standard deviations below the mean (Probability < 0.15%)
        # This ensures we enter only on extreme liquidity gaps/panic dumps, not standard trends.
        self.z_entry_threshold = -3.0
        self.trade_amount = 0.1
        self.min_price_threshold = 1e-8

    def _calculate_stats(self, data):
        """Helper to calculate Mean and Population Standard Deviation."""
        n = len(data)
        if n == 0:
            return 0.0, 0.0
        mean = sum(data) / n
        # Variance = sum((x - mean)^2) / n
        variance = sum((x - mean) ** 2 for x in data) / n
        return mean, math.sqrt(variance)

    def on_price_update(self, prices):
        """
        Analyzes price stream for statistical anomalies using Z-Scores.
        Returns order dict if price is a negative outlier (Oversold).
        """
        for symbol, price_data in prices.items():
            try:
                # 1. Validation
                if not isinstance(price_data, dict):
                    continue
                
                raw_price = price_data.get('priceUsd')
                if raw_price is None:
                    continue
                
                current_price = float(raw_price)
                if current_price < self.min_price_threshold:
                    continue

                # 2. History Management
                symbol_history = self.history[symbol]
                symbol_history.append(current_price)

                # 3. Data Sufficiency Check
                if len(symbol_history) < self.window_size:
                    continue

                # 4. Statistical Calculations
                mean_price, std_dev = self._calculate_stats(symbol_history)

                # Avoid division by zero in low volatility environments
                if std_dev == 0:
                    continue

                # 5. Z-Score Calculation
                # Determines how many standard deviations the current price is from the mean.
                z_score = (current_price - mean_price) / std_dev

                # 6. Execution Logic (Counter-Trend / Mean Reversion)
                # We strictly buy into weakness (Negative Z-Score).
                # This explicitly avoids 'Trend Following' (buying strength) and 'Momentum' (buying velocity).
                if z_score < self.z_entry_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['MEAN_REVERSION', 'STATISTICAL_OVERSOLD']
                    }

            except Exception:
                # Fail-safe for arithmetic or parsing errors
                continue

        return None