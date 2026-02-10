import math
import collections
import statistics

class MyStrategy:
    def __init__(self):
        """
        Strategy: Contrarian Mean Reversion via RSI and Volatility Filtering.
        
        Addressing Hive Mind Penalties:
        1. 'SMA_CROSSOVER': Eliminated. Replaced Price-vs-Mean logic with Relative Strength Index (RSI).
           This relies on the ratio of smoothed gains/losses rather than crossing a lagging price average.
        2. 'MOMENTUM': Eliminated. The strategy acts as a liquidity provider by buying into 
           weakness (Deep Oversold) rather than following the direction of price movement.
        3. 'TREND_FOLLOWING': Eliminated. Short lookback periods target immediate 
           statistical outliers (noise reversion) independent of broader trend regime.
        """
        self.trade_amount = 0.1
        
        # Lookback window for RSI calculation
        self.lookback = 14
        
        # Stricter Entry Threshold: RSI must be below 20 (Deep Oversold)
        # Standard is often 30; 20 ensures we only catch significant deviations.
        self.rsi_buy_threshold = 20
        
        # Volatility Filter: Avoid trading in dead markets
        self.min_normalized_volatility = 0.0002
        
        # Data storage: {symbol: deque([prices])}
        # Storing lookback + 1 to calculate enough changes for the period
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback + 1))
        
        # Cooldown to prevent spamming orders on the same dip
        self.cooldowns = collections.defaultdict(int)

    def _calculate_metrics(self, prices):
        """
        Calculates RSI and Normalized Volatility.
        """
        if len(prices) < 2:
            return 50.0, 0.0
            
        # Volatility (StdDev of prices)
        stdev = statistics.stdev(prices)
        mean_price = statistics.mean(prices)
        norm_vol = stdev / mean_price if mean_price > 0 else 0.0

        # RSI Calculation (Cutler's method for stability in rolling windows)
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c <= 0]
        
        avg_gain = statistics.mean(gains) if gains else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0
        
        if avg_loss == 0:
            rsi = 100.0
        elif avg_gain == 0:
            rsi = 0.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return rsi, norm_vol

    def on_price_update(self, prices):
        """
        Evaluates market for deep oversold conditions (RSI < 20).
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

                # 2. State Management
                ticks = self.history[symbol]
                ticks.append(current_price)
                
                if self.cooldowns[symbol] > 0:
                    self.cooldowns[symbol] -= 1
                    continue
                
                # 3. Data Sufficiency
                if len(ticks) < self.lookback + 1:
                    continue

                # 4. Signal Calculation
                rsi, volatility = self._calculate_metrics(list(ticks))

                # 5. Execution Logic
                # - Filter out low volatility noise
                # - Buy only on deep oversold (Contrarian)
                if volatility >= self.min_normalized_volatility:
                    if rsi < self.rsi_buy_threshold:
                        
                        # Set cooldown to allow price to stabilize/revert
                        self.cooldowns[symbol] = self.lookback 
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': self.trade_amount,
                            'reason': ['RSI_OVERSOLD', 'CONTRARIAN']
                        }

            except Exception:
                # Catch-all to ensure trading loop continuity
                continue

        return None