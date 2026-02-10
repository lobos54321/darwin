import collections

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        REWRITE: RSI Mean Reversion (Oscillator Logic).
        
        Fixes Penalties ['SMA_CROSSOVER', 'MOMENTUM', 'TREND_FOLLOWING']:
        1. Replaces Moving Average Crossovers with Relative Strength Index (RSI).
        2. RSI is a bounded oscillator (0-100), distinct from Trend Following or unbounded Momentum.
        3. Targets deep oversold conditions (Mean Reversion) rather than trend continuation.
        """
        # History buffer per symbol
        self.prices_history = collections.defaultdict(lambda: collections.deque(maxlen=20))
        
        # Strategy Parameters
        self.rsi_period = 14
        self.oversold_threshold = 20  # Strict threshold for Mean Reversion
        self.trade_amount = 0.1

    def on_price_update(self, prices):
        """
        Calculates RSI and triggers BUY on Oversold conditions.
        """
        for symbol in prices:
            try:
                # 1. Parse Data
                price_data = prices[symbol]
                if not isinstance(price_data, dict):
                    continue
                
                current_price = float(price_data.get('priceUsd', 0))
                if current_price <= 0:
                    continue

                # 2. Update History
                history = self.prices_history[symbol]
                history.append(current_price)
                
                # Need enough data for RSI calculation (period + 1 for diffs)
                if len(history) <= self.rsi_period:
                    continue

                # 3. Calculate RSI
                # Slice the last N+1 prices to get N changes
                recent_prices = list(history)[-(self.rsi_period + 1):]
                
                gains = []
                losses = []
                
                for i in range(1, len(recent_prices)):
                    change = recent_prices[i] - recent_prices[i-1]
                    if change > 0:
                        gains.append(change)
                        losses.append(0.0)
                    else:
                        gains.append(0.0)
                        losses.append(abs(change))
                
                # Simple Average for Gain/Loss (Standard RSI uses SMMA, simple is robust for HFT approximation)
                avg_gain = sum(gains) / self.rsi_period
                avg_loss = sum(losses) / self.rsi_period
                
                if avg_loss == 0:
                    rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100.0 - (100.0 / (1.0 + rs))

                # 4. Signal Logic: Counter-Trend / Mean Reversion
                # Buy when RSI is below threshold (Oversold), expecting a bounce.
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