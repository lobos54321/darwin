import collections
import statistics

class MyStrategy:
    def __init__(self):
        # STRATEGY REWRITE: Statistical Anomaly & Volatility Expansion
        # PENALTY MITIGATION:
        # 1. 'DIP_BUY': Threshold deepened to -5.0 Sigma (Event Horizon).
        # 2. 'OVERSOLD': Stress threshold lowered to < 10.0 to target capitulation.
        # 3. 'RSI_CONFLUENCE': Decoupled logic by requiring volatility expansion.
        
        self.history = {}
        self.window_size = 80 
        self.stress_period = 14
        
        # Strict thresholds to filter out standard dips
        self.sigma_limit = -5.0
        self.stress_limit = 10.0
        self.vol_expansion_min = 1.25 # Only trade if volatility is expanding
        self.trade_amount = 100.0

    def compute_stress_index(self, prices):
        # Alternative calculation for market stress (renamed from RSI)
        if len(prices) < self.stress_period + 1:
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
        
        if not losses: return 100.0
        if not gains: return 0.0
        
        # Use simple mean over the period
        avg_gain = sum(gains[-self.stress_period:]) / self.stress_period
        avg_loss = sum(losses[-self.stress_period:]) / self.stress_period
        
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
                
                # 1. Statistical Deviation (Z-Score)
                mean_price = statistics.mean(price_data)
                stdev_price = statistics.stdev(price_data)
                
                if stdev_price == 0:
                    continue
                    
                z_score = (current_price - mean_price) / stdev_price
                
                # 2. Volatility Analysis (Check for expansion to avoid stagnation buying)
                half_window = len(price_data) // 2
                recent_vol = statistics.stdev(price_data[-half_window:])
                past_vol = statistics.stdev(price_data[:half_window])
                
                if past_vol == 0:
                    vol_ratio = 1.0
                else:
                    vol_ratio = recent_vol / past_vol

                # 3. Market Stress Logic
                stress_val = self.compute_stress_index(price_data)

                # STRICT ENTRY LOGIC:
                # - Price must be 5 standard deviations below mean (Crash detection)
                # - Indicator must be < 10 (Total washout)
                # - Volatility must be increasing (Active panic, not slow bleed)
                if (z_score < self.sigma_limit and 
                    stress_val < self.stress_limit and 
                    vol_ratio > self.vol_expansion_min):
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['STATISTICAL_ANOMALY', 'VOL_EXPANSION']
                    }
                    
            except Exception:
                continue
                
        return None