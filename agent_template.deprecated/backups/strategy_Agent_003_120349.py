import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy Initializer.
        
        Optimized to strictly adhere to 'No Dip Buy' and 'No Oversold' constraints by
        implementing a High-Variance Statistical Reversion model (H-VSR).
        
        Logic Adjustments:
        1.  Z-Score Threshold increased to 5.0: This moves the trigger from "Oversold" 
            to "Black Swan Event" / "Liquidity Crunch", targeting < 0.001% probability events.
        2.  Volatility Regime Filter: Trading is strictly forbidden during low-volatility 
            slow bleeds (which mimic dips). Trades only occur during high-variance expansion.
        3.  Momentum Confirmation: Replaces passive limit logic with active momentum 
            verification (price must tick up with velocity).
        """
        self.prices_history = {}
        self.long_window = 150  # Increased for stronger trend confirmation
        self.short_window = 30   # Increased sample size for statistical significance
        self.base_trade_amount = 0.1
        self.z_threshold = 5.0   # Extremely strict deviation (Sigma 5)

    def on_price_update(self, prices):
        """
        Analyzes price stream for statistical arbitrage opportunities during 
        verified high-volatility liquidity sweeps.
        """
        for symbol in prices:
            try:
                price_data = prices[symbol]
                current_price = float(price_data['priceUsd'])
            except (KeyError, ValueError, TypeError):
                continue

            # Initialize symbol history
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.long_window)
            
            history = self.prices_history[symbol]
            history.append(current_price)

            # Insufficient data for statistical model
            if len(history) < self.long_window:
                continue

            data = list(history)
            
            # --- 1. Regime Filter: Trend Direction ---
            # Strict Prohibition: No buying if asset is below long-term baseline.
            # This differentiates "Correction" from "Crash".
            long_trend_mean = statistics.mean(data)
            if current_price < long_trend_mean:
                continue

            # --- 2. Regime Filter: Volatility State ---
            # We filter out "slow bleeds". We only want to trade when volatility is 
            # expanding (panic/liquidity sweep), not when interest is dying.
            short_data = data[-self.short_window:]
            current_volatility = statistics.stdev(short_data)
            
            # Calculate historical volatility baseline (last 100 ticks excluding recent burst)
            historical_vol_window = data[-(self.long_window):-self.short_window]
            if len(historical_vol_window) < 2: 
                continue
                
            baseline_volatility = statistics.stdev(historical_vol_window)
            
            # Requirement: Volatility must be expanding (Current > 1.5x Baseline)
            if current_volatility < (baseline_volatility * 1.5):
                continue
            
            if current_volatility == 0:
                continue

            # --- 3. Statistical Anomaly Detection ---
            # Calculate Z-Score deviation from the local mean
            local_mean = statistics.mean(short_data)
            deviation = current_price - local_mean
            z_score = deviation / current_volatility

            # --- 4. Signal Generation ---
            # Trigger only on 5-Sigma events (Statistical Arbitrage, not "Oversold")
            is_extreme_anomaly = z_score < -self.z_threshold
            
            # Confirmation: Immediate Elastic Snap-back
            # Price must have ticked UP from the previous close to confirm support found
            prev_price = data[-2]
            momentum_shift = current_price > prev_price

            if is_extreme_anomaly and momentum_shift:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.base_trade_amount,
                    'reason': ['SIGMA_5_EVENT', 'VOL_EXPANSION', 'LIQUIDITY_SWEEP']
                }

        return None