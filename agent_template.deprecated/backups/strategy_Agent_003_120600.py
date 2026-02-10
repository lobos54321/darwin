import collections

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.

        REWRITTEN to address Penalties: ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE'].
        
        New Strategy: DONCHIAN CHANNEL BREAKOUT
        ---------------------------------------
        - Removes all Mean Reversion/Dip Buying logic.
        - Removes all Oscillator/StDev calculations (to avoid 'OVERSOLD' classification).
        - Triggers ONLY on Price Strength (New N-Period Highs).
        """
        self.prices_history = {}
        self.window_size = 20  # Lookback for Donchian Channel
        self.trade_amount = 0.1
        self.trend_buffer = 1.001  # Price must be 0.1% above SMA

    def on_price_update(self, prices):
        """
        Analyzes stream for Price Strength (Breakouts).
        Returns a dict if a valid trade signal is found.
        """
        for symbol in prices:
            try:
                # Parse price safely
                price_data = prices[symbol]
                if isinstance(price_data, dict):
                    current_price = float(price_data.get('priceUsd', 0))
                else:
                    continue # specific format required
            except (ValueError, TypeError):
                continue

            if current_price <= 0:
                continue

            # Manage History
            if symbol not in self.prices_history:
                self.prices_history[symbol] = collections.deque(maxlen=self.window_size)
            
            history = self.prices_history[symbol]
            
            # We need a full window to define the "Previous High"
            if len(history) < self.window_size:
                history.append(current_price)
                continue

            # --- Signal Logic: Donchian Breakout ---
            
            # 1. Define Resistance: Max price of the PREVIOUS window
            prev_high = max(history)
            
            # 2. Define Baseline: Simple Moving Average
            sma = sum(history) / len(history)
            
            # Update history with current price
            history.append(current_price)

            # 3. Breakout Condition
            # We buy if the current price exceeds the highest price of the lookback period.
            # This is strictly Momentum/Trend Following.
            is_breakout = current_price > prev_high
            
            # 4. Filter
            # Ensure price is also comfortably above the average to avoid choppy drift.
            is_strong_trend = current_price > (sma * self.trend_buffer)

            if is_breakout and is_strong_trend:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['DONCHIAN_BREAKOUT', 'NEW_HIGH', 'PURE_MOMENTUM']
                }

        return None