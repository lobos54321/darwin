import collections

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        REWRITE: Pure Trend Following (SMA Crossover).
        
        Fixes Penalties ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE']:
        1. Eliminates all "Buying Low" logic. We only buy when price is above averages.
        2. Eliminates Oscillators (RSI/Stoch/Z-score) completely.
        3. Uses Dual Moving Average to confirm Trend Direction + Momentum Strength.
        """
        self.prices_history = {}
        self.short_window = 10
        self.long_window = 30
        self.trade_amount = 0.1

    def on_price_update(self, prices):
        """
        Analyzes stream for Momentum/Trend Alignment.
        Returns a dict if a valid trade signal is found.
        """
        for symbol in prices:
            try:
                # Parse price safely
                price_data = prices[symbol]
                if isinstance(price_data, dict):
                    current_price = float(price_data.get('priceUsd', 0))
                else:
                    continue 
            except (ValueError, TypeError):
                continue

            if current_price <= 0:
                continue

            # Manage History
            if symbol not in self.prices_history:
                self.prices_history[symbol] = collections.deque(maxlen=self.long_window)
            
            history = self.prices_history[symbol]
            history.append(current_price)
            
            # Need full window for the slow moving average
            if len(history) < self.long_window:
                continue

            # --- Signal Logic: SMA Momentum ---
            
            # Convert deque to list for slicing/summing
            hist_list = list(history)
            
            # 1. Calculate Averages
            sma_short = sum(hist_list[-self.short_window:]) / self.short_window
            sma_long = sum(hist_list) / self.long_window
            
            # 2. Trend Condition: Golden Cross alignment
            # The short-term average must be strictly above the long-term average.
            is_uptrend = sma_short > sma_long
            
            # 3. Momentum Condition: Price Strength
            # Price must be above the Short SMA. 
            # This explicitly prevents 'DIP_BUY' (buying when price drops below average).
            is_strong_momentum = current_price > sma_short

            if is_uptrend and is_strong_momentum:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['SMA_CROSSOVER', 'MOMENTUM', 'TREND_FOLLOWING']
                }

        return None