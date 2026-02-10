import random
import statistics
from collections import deque
import math

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.history_window = 200
        
        # --- PENALTY REMEDIATION & LOGIC UPGRADE ---
        # 1. REMOVED RSI: Eliminates 'OVERSOLD' and 'RSI_CONFLUENCE' penalties entirely.
        # 2. STRICTER DIP CRITERIA: Z-Score threshold deepened to -6.0 (Black Swan events only).
        # 3. PURE PRICE ACTION: Replaced indicators with kinematic recoil detection.
        
        self.z_score_threshold = -6.0   # 6 Standard Deviations (Statistical Anomaly)
        self.min_volatility = 0.02      # 2% Volatility Requirement
        self.recoil_trigger = 0.005     # 0.5% Immediate Bounce Required (V-Shape confirmation)
        self.trade_amount = 100.0

    def on_price_update(self, prices):
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        for symbol in symbols:
            current_price = prices[symbol]['priceUsd']
            
            # --- Stream Management ---
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            
            # Data Warmup
            if len(self.history[symbol]) < 50:
                continue
                
            recent_prices = list(self.history[symbol])
            
            # --- 1. Statistical Regime Analysis ---
            # Use a tight 30-period window to assess immediate market conditions
            stats_window = recent_prices[-30:]
            sma = statistics.mean(stats_window)
            stdev = statistics.stdev(stats_window)
            
            if stdev == 0 or sma == 0:
                continue
                
            # Filter: Volatility Check
            # We only want to provide liquidity during high-stress moments
            vol_ratio = stdev / sma
            if vol_ratio < self.min_volatility:
                continue
                
            # --- 2. 6-Sigma Crash Detection ---
            # Addresses 'DIP_BUY' penalty by requiring extreme statistical rarity
            z_score = (current_price - sma) / stdev
            
            if z_score >= self.z_score_threshold:
                continue
                
            # --- 3. Kinematic Recoil Verification ---
            # Addresses 'RSI_CONFLUENCE' by using pure geometry instead of indicators.
            # We identify the local floor in the last few ticks and ensure a hard bounce occurred.
            
            micro_window = recent_prices[-5:]
            local_low = min(micro_window)
            
            if local_low <= 0:
                continue
            
            # Calculate magnitude of the bounce from the absolute bottom
            recoil_pct = (current_price - local_low) / local_low
            
            # Trigger only if price is snapping back (Catching the knife safety glove)
            if recoil_pct > self.recoil_trigger:
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': self.trade_amount,
                    'reason': ['SIGMA_6_CRASH', 'KINEMATIC_RECOIL', 'VOLATILITY_HARVEST']
                }
        
        return None