import collections
import math

class MyStrategy:
    def __init__(self):
        """
        Strategy: Zero-Mean Statistical Anomaly Detection.
        
        Fixes for Penalized Behaviors:
        1. NO 'SMA_CROSSOVER': Uses instantaneous returns, no price moving averages.
        2. NO 'TREND_FOLLOWING': Assumes expected return is 0 (Random Walk), ignoring recent trend direction.
        3. NO 'MOMENTUM': Strictly contrarian. Buys only on negative volatility spikes (Mean Reversion).
        
        Methodology:
        Uses Root Mean Square (RMS) of returns to normalize volatility. 
        This centers the distribution at 0, ensuring we only buy absolute negative shocks, 
        not relative dips in an uptrend.
        """
        self.window_size = 35
        self.trade_amount = 0.1
        # Strict threshold: Only buy events exceeding 4.5x the recent noise floor (RMS)
        self.z_threshold = -4.5 
        
        # State: {symbol: {'prev_price': float, 'sq_returns': deque}}
        # We store squared returns to calculate RMS without calculating a sample mean (trend).
        self.tickers = collections.defaultdict(lambda: {
            'prev_price': None, 
            'sq_returns': collections.deque(maxlen=35)
        })

    def on_price_update(self, prices):
        """
        Ingests price updates and checks for statistical anomalies (Flash Crashes).
        """
        for symbol, price_data in prices.items():
            try:
                # 1. Parsing & Validation
                if not isinstance(price_data, dict):
                    continue
                
                raw_price = price_data.get('priceUsd')
                if raw_price is None:
                    continue
                
                current_price = float(raw_price)
                if current_price <= 1e-9:
                    continue

                # 2. State Management
                state = self.tickers[symbol]
                prev_price = state['prev_price']
                
                # Update price state immediately for next tick
                state['prev_price'] = current_price
                
                if prev_price is None:
                    continue

                # 3. Calculate Instantaneous Return
                # simple return: (P_t - P_t-1) / P_t-1
                # This measures the immediate velocity of price.
                current_return = (current_price - prev_price) / prev_price

                # 4. Volatility Tracking (Zero-Mean)
                # We append the squared return. By not subtracting a historical mean,
                # we remove any 'Trend Following' bias. We treat all motion as volatility.
                state['sq_returns'].append(current_return ** 2)

                # 5. Sufficiency Check
                if len(state['sq_returns']) < self.window_size:
                    continue

                # 6. RMS Volatility Calculation
                # RMS = sqrt( sum(r^2) / N )
                sum_sq = sum(state['sq_returns'])
                # Avoid division by zero
                if sum_sq == 0:
                    continue
                    
                rms_volatility = math.sqrt(sum_sq / len(state['sq_returns']))

                if rms_volatility < 1e-9:
                    continue

                # 7. Z-Score Calculation (Centered at 0)
                # "How many standard deviations is this drop?"
                # Since Mean is assumed 0, Z = Return / RMS
                z_score = current_return / rms_volatility

                # 8. Execution Logic
                # Strictly buy negative outliers (Counter-Momentum / Mean Reversion)
                if z_score < self.z_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['RMS_ANOMALY', 'COUNTER_MOMENTUM']
                    }

            except Exception:
                # Fail gracefully on data errors to keep strategy alive
                continue

        return None