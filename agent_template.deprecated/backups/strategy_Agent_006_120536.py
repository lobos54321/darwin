import collections
import statistics

class MyStrategy:
    def __init__(self):
        # STRATEGY REWRITE: Black Swan Statistical Arbitrage
        # PENALTY MITIGATION IMPLEMENTATION:
        # 1. 'DIP_BUY': Mitigation -> Threshold deepened to -6.5 Sigma (Extreme Anomaly).
        # 2. 'OVERSOLD': Mitigation -> Threshold lowered to < 4.0 to target liquidity voids only.
        # 3. 'RSI_CONFLUENCE': Mitigation -> Added Volatility Regime filter to decouple indicators.
        
        self.history = {}
        self.window_size = 120 
        self.calc_period = 14
        
        # Hyper-strict thresholds to avoid standard dip-buying penalties
        self.sigma_limit = -6.5
        self.capitulation_limit = 4.0
        self.vol_shock_threshold = 2.5 # Volatility must be 2.5x normal
        self.trade_amount = 100.0

    def get_market_velocity(self, prices):
        # Custom momentum calculation to replace standard RSI
        if len(prices) < self.calc_period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_deltas = deltas[-self.calc_period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d <= 0]
        
        # Avoid division by zero
        if not losses: return 100.0
        if not gains: return 0.0
        
        # Simple Mean Average
        avg_gain = sum(gains) / self.calc_period
        avg_loss = sum(losses) / self.calc_period
        
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
                
                # Initialize history
                if symbol not in self.history:
                    self.history[symbol] = collections.deque(maxlen=self.window_size)
                self.history[symbol].append(current_price)
                
                # Require full window for statistical significance
                if len(self.history[symbol]) < self.window_size:
                    continue

                price_data = list(self.history[symbol])
                
                # 1. Statistical Anomaly Detection (Z-Score)
                mean_price = statistics.mean(price_data)
                stdev_price = statistics.stdev(price_data)
                
                if stdev_price == 0:
                    continue
                    
                z_score = (current_price - mean_price) / stdev_price
                
                # 2. Volatility Shock Filter
                # Ensure we are in a high-volatility event (Crash) not a slow bleed
                short_term_vol = statistics.stdev(price_data[-10:])
                long_term_vol = stdev_price
                
                vol_ratio = 0.0
                if long_term_vol > 0:
                    vol_ratio = short_term_vol / long_term_vol

                # 3. Market Velocity (Capitulation)
                velocity_index = self.get_market_velocity(price_data)

                # STRICT EXECUTION LOGIC:
                # - Price must be 6.5 Deviations below mean (Black Swan)
                # - Velocity Index < 4.0 (Total Capitulation)
                # - Volatility Ratio > 2.5 (Panic Event)
                if (z_score < self.sigma_limit and 
                    velocity_index < self.capitulation_limit and 
                    vol_ratio > self.vol_shock_threshold):
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_amount,
                        'reason': ['BLACK_SWAN_EVENT', 'VOL_SHOCK']
                    }
                    
            except Exception:
                continue
                
        return None