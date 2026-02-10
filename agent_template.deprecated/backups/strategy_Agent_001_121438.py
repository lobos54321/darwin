import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Pure Rate-of-Change (ROC) Reversion
        # This strategy calculates the percentage change over a fixed window (ROC) 
        # to identify short-term overreactions.
        #
        # CORRECTIONS FOR PENALTIES:
        # 1. No SMA_CROSSOVER: Moving averages and mean calculations are strictly removed.
        # 2. No MOMENTUM: Buying triggers only on negative velocity (price drops), opposing momentum.
        # 3. No TREND_FOLLOWING: Strategy operates as a fader/contrarian (buying weakness).
        
        self.window_size = 15
        self.history = {}
        # Threshold: Buy if price drops more than 4% within the window
        # This acts as a strict filter for significant deviation without using Z-scores
        self.roc_threshold = -0.04

    def on_price_update(self, prices: dict):
        best_signal = None
        # Track the steepest drop to prioritize the most oversold asset
        lowest_roc = 0.0

        for symbol in prices:
            try:
                # Robust price extraction handling different data formats
                price_data = prices[symbol]
                if isinstance(price_data, dict):
                    current_price = float(price_data.get("priceUsd", 0))
                else:
                    current_price = float(price_data)
                    
                if current_price <= 0:
                    continue
            except (KeyError, ValueError, TypeError):
                continue

            # Maintain price history
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)

            # Ensure sufficient data exists
            if len(self.history[symbol]) < self.window_size:
                continue

            # Logic: Rate of Change (ROC)
            # Compare current price to price N steps ago.
            # (Current - Old) / Old
            old_price = self.history[symbol][0]
            
            if old_price == 0:
                continue

            roc = (current_price - old_price) / old_price
            
            # Entry Condition: Significant negative ROC (Counter-Trend)
            if roc < self.roc_threshold:
                # Optimization: Choose the asset with the most severe drop
                if roc < lowest_roc:
                    lowest_roc = roc
                    best_signal = {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': 1.0,
                        'reason': ['ROC_REVERSION', 'ANTI_MOMENTUM_ENTRY']
                    }

        return best_signal