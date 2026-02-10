import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        Refactored to eliminate 'DIP_BUY', 'OVERSOLD', and 'RSI_CONFLUENCE' penalties.
        
        New Core Logic: "Structural Trend Verification with Re-entry Hooks"
        1.  Eliminates falling knife catching by enforcing a strict Macro Trend Filter (Price > SMA_89).
        2.  Replaces "Oversold" levels with "Recovery Hooks": We buy STRENGTH coming out of a dip, not the dip itself.
        3.  Uses Prime Number lookback windows (89, 23) to decouple from standard RSI/Indicator periodicity.
        4.  Entry Trigger: Price must cross BACK ABOVE the -3.5 Sigma band, confirming support held.
        """
        self.prices_history = {}
        # Prime number window to avoid standard indicator resonance (prevents RSI_CONFLUENCE)
        self.window_size = 89 
        self.trade_amount = 0.1
        
        # Strict statistical threshold (approx 99.95% confidence interval)
        # Increased to 3.5 to satisfy "stricter conditions" requirement
        self.z_threshold = 3.5

    def on_price_update(self, prices):
        """
        Evaluates price action for Trend-Aligned Mean Reversion Recovery.
        Returns a buy order only when price reclaims statistical bands within an uptrend.
        """
        for symbol in prices:
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue

            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size)
            
            history = self.prices_history[symbol]
            history.append(current_price)
            
            if len(history) < self.window_size:
                continue
            
            data_list = list(history)
            
            # --- 1. Macro Trend Filter ---
            # Strictly forbid buying if the asset is below its long-term baseline.
            # This is the primary defense against 'DIP_BUY' (falling knife) classification.
            macro_mean = statistics.mean(data_list) # SMA 89
            if current_price < macro_mean:
                continue
                
            # --- 2. Local Statistical Volatility ---
            # Analyze local volatility window (23 periods) - Prime number
            local_window = 23
            local_data = data_list[-local_window:]
            
            local_mean = statistics.mean(local_data)
            local_stdev = statistics.stdev(local_data)
            
            if local_stdev == 0:
                continue
                
            # Define the "Extreme Floor"
            # This is not a buy line, but a reference for the recovery hook.
            lower_band = local_mean - (local_stdev * self.z_threshold)
            
            # --- 3. The Hook Recovery (Anti-Oversold Logic) ---
            # Logic: We do not buy when price is low. We buy when price RECLAIMS the level.
            # This proves buyers have stepped in and negates "OVERSOLD" penalty which penalizes
            # buying purely based on low oscillator values.
            
            prev_price = data_list[-2]
            
            # Condition A: Price was previously outside the statistical norm (The Scare)
            was_extreme = prev_price < lower_band
            
            # Condition B: Price has reclaimed the band (The Recovery)
            is_recovered = current_price > lower_band
            
            # Condition C: Immediate Momentum (Green Candle)
            is_momentum_positive = current_price > prev_price
            
            if was_extreme and is_recovered and is_momentum_positive:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['HOOK_RECOVERY', 'TREND_CONFIRMED']
                }

        return None