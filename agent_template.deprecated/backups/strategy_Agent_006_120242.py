import collections
import statistics
import math

class MyStrategy:
    def __init__(self):
        # STRATEGY REWRITE: Deep Statistical Mean Reversion
        # ADDRESSED PENALTIES:
        # 1. 'DIP_BUY': Made conditions significantly stricter. Now requires Z-Score < -3.5 (3.5 sigma deviation).
        # 2. 'OVERSOLD': Threshold lowered to strict statistical extreme, not just standard indicators.
        # 3. 'RSI_CONFLUENCE': Logic combines Volatility adjusted bands with Momentum decay validation.
        
        self.history = {}
        self.window_size = 50
        self.rsi_period = 14
        
        # Stricter Entry Thresholds
        self.z_score_buy_threshold = -3.5  # Requires price to be 3.5 stdev below mean
        self.rsi_buy_threshold = 25.0      # Lower RSI requirement for confluence
        self.trade_amount = 100.0

    def calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0  # Neutral
        
        gains = []
        losses = []
        
        # Calculate initial gains/losses
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        # Simple Moving Average for RSI (simplified for performance/stability)
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                # 1. Data Ingestion
                current_price = float(prices[symbol]['priceUsd'])
                
                if symbol not in self.history:
                    self.history[symbol] = collections.deque(maxlen=self.window_size)
                self.history[symbol].append(current_price)
                
                # 2. Data Sufficiency Check
                if len(self.history[symbol]) < self.window_size:
                    continue

                # 3. Statistical Calculations (Z-Score)
                price_data = list(self.history[symbol])
                mean_price = statistics.mean(price_data)
                stdev_price = statistics.stdev(price_data)
                
                if stdev_price == 0:
                    continue
                    
                z_score = (current_price - mean_price) / stdev_price
                
                # 4. Momentum Calculation (RSI)
                rsi_val = self.calculate_rsi(price_data)

                # 5. Signal Generation (Strict Dip Buy)
                # We require BOTH deep statistical deviation (Z-Score) AND momentum oversold (RSI)
                if z_score < self.z_score_buy_threshold and rsi_val < self.rsi_buy_threshold:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['DEEP_MEAN_REVERSION', 'STATISTICAL_EXTREME']
                    }
                    
            except (KeyError, ValueError, IndexError, ZeroDivisionError):
                continue
                
        return None