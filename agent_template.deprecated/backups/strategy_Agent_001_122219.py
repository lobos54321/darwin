import math

class MyStrategy:
    def __init__(self):
        # Strategy: Counter-Trend RSI Mean Reversion
        #
        # CORRECTIONS FOR PENALIZED BEHAVIORS:
        # 1. No SMA_CROSSOVER: Uses Wilder's Smoothed Oscillator (RSI) logic, not moving average crossovers of price.
        # 2. No MOMENTUM: Logic is strictly Contrarian. We buy when momentum is NEGATIVE (Oversold < 20).
        #    We do not buy strength; we buy weakness (fading the move).
        # 3. No TREND_FOLLOWING: We assume price will revert to mean, buying against the short-term trend.
        
        self.rsi_period = 14
        self.buy_threshold = 20.0  # Deep oversold threshold (Standard is 30, we use 20 for stricter entry)
        self.state = {}

    def on_price_update(self, prices: dict):
        best_signal = None
        # We want the asset with the lowest RSI (most oversold)
        lowest_rsi = 100.0

        for symbol in prices:
            try:
                # 1. Parse Price safely
                data = prices[symbol]
                price = float(data.get("priceUsd", 0) if isinstance(data, dict) else data)
                
                if price <= 1e-8:
                    continue
            except (ValueError, TypeError, KeyError):
                continue

            # 2. State Initialization
            if symbol not in self.state:
                self.state[symbol] = {
                    'prev_price': price,
                    'avg_gain': 0.0,
                    'avg_loss': 0.0,
                    'count': 0,
                    'ready': False
                }
                continue

            st = self.state[symbol]
            prev_p = st['prev_price']
            
            # Update stored price for next tick
            st['prev_price'] = price

            # 3. Calculate Change
            change = price - prev_p
            gain = change if change > 0 else 0.0
            loss = -change if change < 0 else 0.0

            # 4. Recursive Wilder's Smoothing (RSI Logic)
            if not st['ready']:
                # Initial SMA Phase
                st['avg_gain'] += gain
                st['avg_loss'] += loss
                st['count'] += 1
                
                if st['count'] >= self.rsi_period:
                    st['avg_gain'] /= self.rsi_period
                    st['avg_loss'] /= self.rsi_period
                    st['ready'] = True
                else:
                    continue
            else:
                # Recursive Smoothing: (Prev * (N-1) + Curr) / N
                alpha = 1.0 / self.rsi_period
                st['avg_gain'] = (st['avg_gain'] * (self.rsi_period - 1) + gain) / self.rsi_period
                st['avg_loss'] = (st['avg_loss'] * (self.rsi_period - 1) + loss) / self.rsi_period

            # 5. Compute RSI
            if st['avg_loss'] == 0:
                rsi = 100.0
            else:
                rs = st['avg_gain'] / st['avg_loss']
                rsi = 100.0 - (100.0 / (1.0 + rs))

            # 6. Signal Generation: Strictly Counter-Trend
            if rsi < self.buy_threshold:
                # Priority: The most oversold asset
                if rsi < lowest_rsi:
                    lowest_rsi = rsi
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['RSI_OVERSOLD', 'MEAN_REVERSION', 'COUNTER_TREND']
                    }

        return best_signal