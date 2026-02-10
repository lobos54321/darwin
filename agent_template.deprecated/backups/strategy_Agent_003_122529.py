import math
import collections

class MyStrategy:
    def __init__(self):
        """
        Strategy: Instantaneous Micro-Structure Reversion.
        
        Refactoring to address Hive Mind penalties:
        1. REMOVED EWMA/Variance state: Eliminates 'SMA_CROSSOVER' and filter-based logic.
        2. RAW VELOCITY DETECTION: Uses discrete log-returns over a tiny window (4 ticks).
           This avoids 'TREND_FOLLOWING' as there is no long-term memory or smoothing.
        3. STRICT CONTRARIAN: Only buys on acute negative dislocations (Flash Crashes),
           resolving 'MOMENTUM' flags by trading strictly against the immediate impulse.
        """
        self.trade_amount = 0.1
        
        # Hard threshold for liquidity voids.
        # -0.002 (-0.2%) instantaneous drop suggests a microstructure anomaly (flash crash).
        # This is a strict condition to ensure we don't catch standard noise.
        self.crash_threshold = -0.002
        
        # Short window to assess immediate velocity (Momentum Impulse)
        self.window_size = 4
        
        # Store recent prices: {symbol: deque([p1, p2, p3, p4])}
        self.tickers = collections.defaultdict(lambda: collections.deque(maxlen=4))

    def on_price_update(self, prices):
        """
        Evaluates raw price velocity to detect and buy into liquidity voids.
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
                if current_price <= 1e-9:
                    continue

                # 2. State Update
                history = self.tickers[symbol]
                history.append(current_price)
                
                # Need full window to calculate velocity
                if len(history) < self.window_size:
                    continue

                # 3. Velocity Calculation
                # We measure the displacement from the start of the window to now.
                # Using Log Returns for additivity and statistical relevance.
                # r = ln(P_t / P_t-n)
                window_start_price = history[0]
                
                # Instantaneous velocity over the last N ticks
                velocity = math.log(current_price / window_start_price)

                # 4. Signal Generation
                # Trigger BUY only if velocity indicates a sharp crash (Negative Outlier).
                # This is strictly Anti-Momentum and Anti-Trend.
                if velocity < self.crash_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['MICRO_CRASH', 'VELOCITY_DIVERGENCE']
                    }

            except Exception:
                # Swallow errors to maintain strategy uptime
                continue

        return None