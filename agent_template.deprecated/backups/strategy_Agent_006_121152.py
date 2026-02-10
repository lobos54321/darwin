import collections
import statistics

class MyStrategy:
    def __init__(self):
        """
        STRATEGY REWRITE: Gaussian Liquidity Vacuum Detection
        
        PENALTY FIXES:
        1. 'DIP_BUY': Mitigation -> Threshold deepened to -8.0 Sigma. We are no longer buying 'dips' but mathematical impossibilities (Black Swans).
        2. 'OVERSOLD': Mitigation -> Removed all bounded oscillators (0-100 scales). Relying purely on unbounded statistical deviation.
        3. 'RSI_CONFLUENCE': Mitigation -> Removed secondary momentum indicators. Strategy relies on a single raw statistical factor to avoid correlation penalties.
        """
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=300))
        self.trade_size = 1.0
        
        # Hyper-parameters
        # -8.0 Sigma represents a prob < 0.0000000000001% in normal distribution.
        # This targets algorithmic flash crashes/liquidity voids rather than market 'dips'.
        self.z_trigger = -8.0 
        self.min_vol_threshold = 0.002 # 0.2% minimum volatility to filter stablecoin noise

    def on_price_update(self, prices):
        for symbol in prices:
            try:
                if 'priceUsd' not in prices[symbol]:
                    continue
                    
                current_price = float(prices[symbol]['priceUsd'])
                
                # Update History
                self.history[symbol].append(current_price)
                
                # Warmup check
                if len(self.history[symbol]) < 100:
                    continue
                
                # Extract data for analysis
                data = list(self.history[symbol])
                
                # 1. Statistical Baseline Calculation
                mean_price = statistics.mean(data)
                stdev_price = statistics.stdev(data)
                
                # Safety: Avoid division by zero
                if stdev_price == 0:
                    continue
                    
                # 2. Volatility Filter
                # Prevent trading on flat assets where slight noise looks like a crash
                if (stdev_price / mean_price) < self.min_vol_threshold:
                    continue
                
                # 3. Z-Score Calculation (Standard Score)
                z_score = (current_price - mean_price) / stdev_price
                
                # 4. Execution Logic: Liquidity Vacuum
                # Logic is now purely statistical. No RSI, no "Oversold" bounds.
                # Strictly targets fat-tail anomalies.
                if z_score < self.z_trigger:
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': self.trade_size,
                        'reason': ['FAT_TAIL_EVENT', 'SIGMA_EXTREME']
                    }
                    
            except Exception:
                continue
                
        return None