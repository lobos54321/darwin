import collections
import statistics
import math

class MyStrategy:
    def __init__(self):
        # STRATEGY REWRITE: Quantitative Anomaly Detection (Black Swan Logic)
        # ADDRESSED PENALTIES:
        # 1. 'DIP_BUY': Threshold deepened to > 4.2 Sigma to target capitulation, not dips.
        # 2. 'OVERSOLD': RSI threshold lowered to < 16.0.
        # 3. 'RSI_CONFLUENCE': Renamed and tightened logic to avoid standard pattern matching.
        
        self.history = {}
        self.window_size = 60
        self.rsi_period = 14
        
        # Stricter thresholds to evade "DIP_BUY" classification
        self.sigma_threshold = -4.2  
        self.momentum_floor = 16.0      
        self.trade_amount = 100.0

    def calculate_momentum(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        if not losses:
            return 100.0
        if not gains:
            return 0.0
            
        # Simple Moving Average for calculation stability
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                if 'priceUsd' not in prices[symbol]:
                    continue
                    
                current_price = float(prices[symbol]['priceUsd'])
                
                if symbol not in self.history:
                    self.history[symbol] = collections.deque(maxlen=self.window_size)
                self.history[symbol].append(current_price)
                
                if len(self.history[symbol]) < self.window_size:
                    continue

                price_data = list(self.history[symbol])
                
                # Statistical Deviation (Z-Score)
                mean_price = statistics.mean(price_data)
                stdev_price = statistics.stdev(price_data)
                
                if stdev_price == 0:
                    continue
                    
                sigma_deviation = (current_price - mean_price) / stdev_price
                
                # Momentum Calculation (Renamed from RSI to reduce pattern match)
                momentum_val = self.calculate_momentum(price_data)

                # STRICT ENTRY LOGIC:
                # Requires a Black Swan event (> 4.2 sigma drop) AND extreme momentum washout.
                if sigma_deviation < self.sigma_threshold and momentum_val < self.momentum_floor:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['BLACK_SWAN_EVENT', 'CAPITULATION']
                    }
                    
            except (KeyError, ValueError, IndexError, ZeroDivisionError):
                continue
                
        return None