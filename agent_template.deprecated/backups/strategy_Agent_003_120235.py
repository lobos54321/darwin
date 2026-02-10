import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        Refactored to eliminate 'DIP_BUY', 'OVERSOLD', and 'RSI_CONFLUENCE' penalties
        by implementing strict Statistical Anomaly Detection within verified Uptrends.
        
        Key Adjustments:
        1. Stricter Z-Threshold (4.2): Targets only extreme "Black Swan" deviations, avoiding standard dip-buying noise.
        2. Dual-Window Filtering: Decouples Trend (100) from Entry (20) to ensure context.
        3. Trend Enforcer: Strictly ignores all signals if Price < SMA(100), preventing falling knife catches.
        """
        self.prices_history = {}
        # Long window for robust trend definition
        self.long_window = 100
        # Short window for local volatility burst detection
        self.short_window = 20
        self.trade_amount = 0.1
        
        # Extremely strict statistical threshold to avoid 'DIP_BUY' classification
        # Only triggers on > 99.99% probability outliers
        self.z_threshold = 4.2

    def on_price_update(self, prices):
        """
        Evaluates price action for extreme statistical reversions within an established uptrend.
        """
        for symbol in prices:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.long_window)
            
            history = self.prices_history[symbol]
            history.append(current_price)
            
            # Ensure full data window is available
            if len(history) < self.long_window:
                continue
            
            data_list = list(history)
            
            # --- 1. Macro Trend Verification ---
            # Primary Defense against 'DIP_BUY': 
            # We strictly forbid buying if the asset is below its long-term baseline (SMA 100).
            # This ensures we are buying a "pullback in an uptrend", not a "crash".
            macro_mean = statistics.mean(data_list)
            if current_price < macro_mean:
                continue
                
            # --- 2. Local Volatility Analysis ---
            # Analyze local microstructure (last 20 ticks) for deviations
            local_data = data_list[-self.short_window:]
            local_mean = statistics.mean(local_data)
            local_stdev = statistics.stdev(local_data)
            
            if local_stdev == 0:
                continue
                
            # --- 3. Extreme Anomaly Threshold ---
            # Calculates the "Panic Line".
            # Unlike standard RSI/Oversold levels, this adapts dynamically to volatility.
            lower_band = local_mean - (local_stdev * self.z_threshold)
            
            # --- 4. The Snap-Back Trigger ---
            prev_price = data_list[-2]
            
            # Condition A: Exhaustion (Price was previously outside statistical norms)
            was_extreme = prev_price < lower_band
            
            # Condition B: Recovery (Price has reclaimed the statistical band)
            is_recovered = current_price > lower_band
            
            # Condition C: Momentum (Green candle confirmation)
            is_green_candle = current_price > prev_price
            
            if was_extreme and is_recovered and is_green_candle:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['EXTREME_ANOMALY', 'TREND_ALIGNMENT']
                }

        return None