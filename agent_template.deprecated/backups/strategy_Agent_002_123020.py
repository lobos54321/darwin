import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Data Management
        self.history = {}
        self.window_size = 50
        self.trade_amount = 100.0
        
        # --- STRATEGY PARAMETERS ---
        # Fixed logic to avoid 'MOMENTUM' and 'TREND_FOLLOWING'.
        # We switch to a pure Mean Reversion approach.
        # We look for statistical anomalies (Z-Score) confirmed by 
        # oscillator extremes (RSI), strictly trading against the move.
        self.rsi_period = 14
        self.rsi_oversold = 30.0
        self.z_score_buy = -2.5

    def _calculate_rsi(self, prices):
        """
        Calculates RSI (Relative Strength Index) on the provided window.
        Uses Cutler's RSI (Simple Moving Average of Gains/Losses) for 
        stability in a rolling window context.
        """
        if len(prices) < 2:
            return 50.0

        gains = []
        losses = []
        
        # Calculate changes
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        
        # Analyze only the relevant period
        n = min(len(gains), self.rsi_period)
        if n == 0:
            return 50.0
            
        avg_gain = sum(gains[-n:]) / n
        avg_loss = sum(losses[-n:]) / n
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # Parse Price
                data = prices[symbol]
                price = float(data['priceUsd']) if isinstance(data, dict) else float(data)
            except (KeyError, ValueError, TypeError):
                continue

            if price <= 0:
                continue

            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(price)

            if len(self.history[symbol]) < self.window_size:
                continue

            price_series = list(self.history[symbol])

            # --- MEAN REVERSION LOGIC ---
            # 1. Z-Score: Distance from the Mean in Standard Deviations.
            # This identifies outliers without assuming a trend (unlike Linear Regression).
            # It avoids 'SMA_CROSSOVER' (no crossing of two lines) and 'TREND_FOLLOWING' 
            # (since we buy when price is statistically low, fading the move).
            mean_price = statistics.mean(price_series)
            stdev_price = statistics.stdev(price_series)
            
            if stdev_price == 0:
                continue
                
            z_score = (price - mean_price) / stdev_price

            # 2. RSI Check
            # Confirms the dip is an oversold condition, not just low volatility.
            # Low RSI (< 30) ensures we are not buying into 'MOMENTUM'.
            rsi = self._calculate_rsi(price_series)

            # ENTRY SIGNAL
            # Buy only if price is severely depressed (Z < -2.5) AND RSI is Oversold.
            if z_score < self.z_score_buy and rsi < self.rsi_oversold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['MEAN_REVERSION', 'Z_SCORE_DIP', 'RSI_OVERSOLD']
                }

        return None