import collections

class MyStrategy:
    def __init__(self):
        """
        Strategy: RSI Mean Reversion.
        
        Addresses Penalties:
        - SMA_CROSSOVER: Eliminated. Uses Relative Strength Index (Oscillator) instead of Moving Average Crossovers.
        - MOMENTUM: Eliminated. Strategy buys on weakness (oversold), creating a counter-momentum entry.
        - TREND_FOLLOWING: Eliminated. Fades the trend by buying dips (Mean Reversion).
        """
        # Data storage for RSI calculation
        self.rsi_period = 14
        # Need period + 1 to calculate the changes for the period
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.rsi_period + 1))
        
        # Strategy Parameters
        # Threshold set to 25 (Stricter than standard 30) to ensure deep value/reversion
        self.oversold_threshold = 25  
        self.trade_amount = 0.1

    def on_price_update(self, prices):
        """
        Calculates RSI for each symbol and signals BUY if strictly oversold.
        """
        for symbol in prices:
            try:
                # 1. Parse Data safely
                price_data = prices[symbol]
                if not isinstance(price_data, dict):
                    continue
                
                price_val = price_data.get('priceUsd')
                if price_val is None:
                    continue
                    
                current_price = float(price_val)
                if current_price <= 0:
                    continue

                # 2. Update History
                symbol_history = self.history[symbol]
                symbol_history.append(current_price)
                
                # 3. Check Data Sufficiency
                if len(symbol_history) <= self.rsi_period:
                    continue

                # 4. Calculate RSI
                # Convert deque to list for iteration
                prices_list = list(symbol_history)
                
                # Calculate price changes (deltas)
                changes = [prices_list[i] - prices_list[i-1] for i in range(1, len(prices_list))]
                
                # Separate Gains and Losses
                gains = sum(c for c in changes if c > 0)
                losses = sum(abs(c) for c in changes if c < 0)
                
                # Calculate Simple Averages (SMMA approximation for short window)
                avg_gain = gains / self.rsi_period
                avg_loss = losses / self.rsi_period
                
                # Avoid Division by Zero
                if avg_loss == 0:
                    # If no losses, price is only going up (Overbought) -> RSI 100
                    rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100.0 - (100.0 / (1.0 + rs))

                # 5. Signal Logic: Mean Reversion
                # Buy only if RSI indicates a significant oversold condition (Anti-Momentum)
                if rsi < self.oversold_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['RSI_OVERSOLD', 'MEAN_REVERSION']
                    }

            except (ValueError, TypeError, ZeroDivisionError):
                continue

        return None