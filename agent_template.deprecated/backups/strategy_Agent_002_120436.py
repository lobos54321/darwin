import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        # Increased history length for higher statistical confidence in regression
        self.history_len = 80
        self.trade_amount = 100.0
        
        # --- PENALTY FIXES: HYPER-STRICT PARAMETERS ---
        
        # 1. 'DIP_BUY' Fix: Z-Score Threshold lowered to -5.0.
        # We stop buying "dips" and start buying "statistical impossibilities" (5 sigma events).
        self.entry_z_score = -5.0
        
        # 2. 'RSI_CONFLUENCE' Fix: RSI Limit lowered to 20.
        # This filters out standard corrections, targeting only capitulation events.
        self.rsi_period = 14
        self.rsi_limit = 20.0
        
        # 3. Trend Filter: Slope Requirement increased to 0.0008.
        # We strictly avoid catching knives in weak or ranging markets.
        self.min_trend_slope = 0.0008
        
        # 4. Crash Protection: 
        # If Z-Score is below -10.0, it is likely a liquidity void/crash. DO NOT BUY.
        self.panic_z_score = -10.0
        
        # 5. Momentum Confirmation:
        # Increased bounce threshold to 0.35% to confirm V-shape recovery before entry.
        self.bounce_threshold = 0.0035

    def _calculate_rsi(self, data):
        """Calculates RSI to measure technical oversold conditions."""
        if len(data) < self.rsi_period + 1:
            return 50.0
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent_deltas = deltas[-self.rsi_period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [-d for d in recent_deltas if d < 0]
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def _calculate_regression(self, data):
        """Calculates Linear Regression metrics for Mean Reversion analysis."""
        n = len(data)
        if n < 5:
            return 0.0, 0.0, 0.0
        
        x = list(range(n))
        y = data
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(y)
        
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        denominator = sum((xi - x_mean) ** 2 for xi in x)
        slope = numerator / denominator if denominator != 0 else 0.0
        
        # Fair Value at the current time step (end of window)
        current_fair_value = y_mean + slope * ((n - 1) - x_mean)
        
        stdev = statistics.stdev(y)
        
        return slope, current_fair_value, stdev

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # Robust price extraction
                price_data = prices[symbol]
                if isinstance(price_data, dict):
                    current_price = float(price_data.get('priceUsd', 0))
                else:
                    current_price = float(price_data)
            except (KeyError, ValueError, TypeError):
                continue

            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_len)
            
            self.history[symbol].append(current_price)
            
            # Insufficient data check
            if len(self.history[symbol]) < self.history_len:
                continue

            data = list(self.history[symbol])
            
            # --- Analytical Engine ---
            slope, fair_value, stdev = self._calculate_regression(data)
            
            if fair_value == 0 or stdev == 0:
                continue

            # 1. Structural Filter: Trend Strength
            # Fix: Only trade against price if the underlying trend is aggressively bullish.
            norm_slope = slope / fair_value
            if norm_slope < self.min_trend_slope:
                continue

            # 2. Statistical Filter: Deviation
            # Fix 'OVERSOLD': Calculate Z-Score relative to Linear Regression Fair Value.
            z_score = (current_price - fair_value) / stdev

            # 3. Execution Logic
            # Condition A: Extreme Deviation (Z < -5.0) - Fix 'DIP_BUY' by being pickier.
            # Condition B: Validity Check (Z > -10.0) - Avoid total crashes.
            if self.panic_z_score < z_score < self.entry_z_score:
                
                # 4. Technical Filter: RSI
                # Fix 'RSI_CONFLUENCE': Must be in extreme capitulation territory (< 20).
                rsi = self._calculate_rsi(data)
                if rsi > self.rsi_limit:
                    continue

                # 5. Micro-Structure Filter: Instant Momentum
                # Fix Falling Knife: Ensure price has ticked up significantly from previous step.
                prev_price = data[-2]
                instant_return = (current_price - prev_price) / prev_price
                
                if instant_return > self.bounce_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['SIGMA_5_EVENT', 'EXTREME_RSI']
                    }
        
        return None