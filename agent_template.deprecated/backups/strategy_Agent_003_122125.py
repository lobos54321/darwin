import collections
import math

class MyStrategy:
    def __init__(self):
        """
        Strategy: Instantaneous Return Anomaly Detection (Statistical Arbitrage).
        
        Refactored to Eliminate Penalized Behaviors:
        - Removes 'SMA_CROSSOVER': Logic relies on rate-of-change (returns), not price averages.
        - Removes 'TREND_FOLLOWING': strictly buys negative outliers (counter-trend).
        - Removes 'MOMENTUM': Buys against the velocity vector (mean reversion).
        
        Logic:
        Calculates the statistical deviation of the *current tick's return* against 
        recent volatility. Buys only when the immediate price drop is a statistical 
        outlier (e.g., 4 sigma event).
        """
        self.window_size = 40
        self.trade_amount = 0.1
        # Increased strictness: Only buy 4+ standard deviation drops (Flash Crashes)
        self.z_entry_threshold = -4.0 
        
        # State: Stores previous price and rolling returns for volatility calculation
        # Structure: {symbol: {'prev_price': float, 'returns': deque}}
        self.tickers = collections.defaultdict(lambda: {
            'prev_price': None, 
            'returns': collections.deque(maxlen=40)
        })

    def on_price_update(self, prices):
        """
        Analyzes price stream for return anomalies.
        Returns order dict if instantaneous return is a negative outlier.
        """
        for symbol, price_data in prices.items():
            try:
                # 1. Data Parsing & Validation
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
                
                # Always update price for the next tick
                state['prev_price'] = current_price
                
                if prev_price is None:
                    continue

                # 3. Calculate Instantaneous Return
                # Using simple percentage change: (P_t - P_t-1) / P_t-1
                current_return = (current_price - prev_price) / prev_price
                state['returns'].append(current_return)

                # 4. Sufficiency Check
                if len(state['returns']) < self.window_size:
                    continue

                # 5. Volatility Analysis (On Returns, not Price)
                # Calculates how volatile the asset is currently.
                history = state['returns']
                mean_return = sum(history) / len(history)
                
                variance = sum((r - mean_return) ** 2 for r in history) / len(history)
                std_dev = math.sqrt(variance)

                # Filter out zero volatility periods to avoid division errors
                if std_dev < 1e-9:
                    continue

                # 6. Z-Score of the RETURN
                # "How anomalous is this specific price movement compared to recent noise?"
                # A low Z-score on Price is "Price is cheap".
                # A low Z-score on Return is "Price crashed fast".
                return_z_score = (current_return - mean_return) / std_dev

                # 7. Execution Logic
                # Strictly counter-trend. If return is a massive negative outlier, we buy the liquidity gap.
                if return_z_score < self.z_entry_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['RETURN_ANOMALY', 'FLASH_DIP']
                    }

            except Exception:
                # Resilience against data errors
                continue

        return None