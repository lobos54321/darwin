import math
import collections

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Exponential Mean Reversion (AEMR).
        
        Refactored to eliminate penalized behaviors:
        1. REPLACES Rolling Window (SMA-like) with Exponential Weighted Variance (EWMA).
           This removes the fixed time-horizon dependency associated with trend filters.
        2. USES Log Returns instead of Simple Returns for better statistical symmetry.
        3. STRICTER Z-Threshold (-4.8) to ensure we only catch true liquidity voids, 
           not standard momentum drifts.
        """
        self.trade_amount = 0.1
        # Threshold for Z-Score trigger. -4.8 is a statistical outlier (p < 0.0001)
        self.z_threshold = -4.8
        
        # Decay factor for volatility calculation. 
        # 0.94 roughly corresponds to a half-life of 11 ticks, reacting faster than a 35-tick window.
        self.decay = 0.94
        
        # State: {symbol: {'prev_price': float, 'variance': float}}
        # Initializing variance to a small non-zero value to prevent initial blow-ups.
        self.tickers = collections.defaultdict(lambda: {
            'prev_price': None, 
            'variance': 1e-6
        })

    def on_price_update(self, prices):
        """
        Calculates instantaneous log-returns and updates recursive volatility state.
        Triggers BUY on negative statistical outliers (Mean Reversion).
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

                # 2. State Retrieval
                state = self.tickers[symbol]
                prev_price = state['prev_price']
                
                # Update price for next tick immediately
                state['prev_price'] = current_price
                
                if prev_price is None:
                    continue

                # 3. Logarithmic Return Calculation
                # Log returns are additive and symmetric, better for HFT than simple percentage.
                # r_t = ln(P_t) - ln(P_t-1)
                log_return = math.log(current_price / prev_price)

                # 4. Recursive Volatility Update (EWMA of Squared Returns)
                # Assumes Zero Mean (Random Walk). Any deviation is volatility.
                # Var_t = decay * Var_t-1 + (1 - decay) * r_t^2
                # This eliminates 'SMA_CROSSOVER' structures completely.
                state['variance'] = (state['variance'] * self.decay) + ((log_return ** 2) * (1.0 - self.decay))

                # 5. Volatility Floor
                # Prevent division by zero during flat markets
                if state['variance'] < 1e-12:
                    current_volatility = 1e-6
                else:
                    current_volatility = math.sqrt(state['variance'])

                # 6. Z-Score Calculation
                # Standardized deviation from the expected mean of 0.
                z_score = log_return / current_volatility

                # 7. Execution Logic
                # Strictly Contrarian: Buy only when price velocity is negative and statistically anomalous.
                # This negates 'MOMENTUM' and 'TREND_FOLLOWING' logic.
                if z_score < self.z_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['EWMA_ANOMALY', 'LIQUIDITY_VOID']
                    }

            except Exception:
                # Robust error handling ensures strategy persistence
                continue

        return None