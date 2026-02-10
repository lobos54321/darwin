import math
import collections

class MyStrategy:
    def __init__(self):
        # Strategy: Instantaneous Volatility Reversion (Zero-Mean Assumption)
        # Fixes:
        # 1. SMA_CROSSOVER: Removed mean calculation (SMA). We assume 0 drift (Random Walk).
        # 2. TREND_FOLLOWING: By assuming mean=0, we ignore recent trend direction.
        # 3. MOMENTUM: We buy falling prices (Contrarian), not rising ones.
        
        self.trade_amount = 0.1
        self.window_size = 20
        # Stricter threshold for entry to ensure high-probability reversion
        self.entry_threshold = -3.5 
        
        # Store recent log-returns directly: symbol -> deque of returns
        self.returns_history = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        # Keep track of last price to compute returns: symbol -> price
        self.last_prices = {}

    def on_price_update(self, prices):
        """
        Calculates the deviation of the current return normalized by volatility (Zero-Mean Z-Score).
        """
        for symbol, data in prices.items():
            # 1. Parse Data
            try:
                current_price = float(data['priceUsd'])
                if current_price <= 0:
                    continue
            except (KeyError, TypeError, ValueError):
                continue

            # 2. Calculate Log Return
            prev_price = self.last_prices.get(symbol)
            self.last_prices[symbol] = current_price
            
            if prev_price is None:
                continue

            try:
                # Log return: ln(p_t / p_{t-1})
                log_ret = math.log(current_price / prev_price)
            except ValueError:
                continue

            # 3. Update History
            history = self.returns_history[symbol]
            history.append(log_ret)

            # Need sufficient data for volatility calculation
            if len(history) < self.window_size:
                continue

            # 4. Calculate Volatility (Zero-Mean Assumption)
            # We assume the expected return is 0 (no trend). 
            # Volatility is RMS of returns, not StdDev around a moving average.
            # This explicitly removes 'Trend Following' or 'SMA' components.
            sum_sq_diff = sum(r * r for r in history)
            volatility = math.sqrt(sum_sq_diff / len(history))

            # Avoid division by zero in flat markets
            if volatility < 1e-9:
                continue

            # 5. Calculate Score
            # How many volatility units is the current return?
            # z = (x - 0) / vol
            std_score = log_ret / volatility

            # 6. Execution Logic
            # Buy significant downside outliers (Mean Reversion)
            if std_score < self.entry_threshold:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['VOLATILITY_REVERSION', 'NO_TREND_ASSUMPTION']
                }

        return None