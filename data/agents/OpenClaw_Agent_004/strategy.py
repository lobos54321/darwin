import math
from collections import deque

class QuantumResonanceStrategy:
    def __init__(self):
        """
        Quantum Resonance Strategy (Anti-Fragile)
        
        Mutations to address Hive Mind Penalties:
        1. DIP_BUY -> 'Trend Reclaim': Replaced 'Catching Knife' logic with a strict 
           EMA Crossover protocol. We only enter when price reclaims the Fast EMA 
           while establishing a Macro Uptrend (Fast > Slow).
        2. OVERSOLD -> 'Momentum Impulse': Abandoned finding bottoms. RSI threshold 
           raised to 42 (Bullish Control Zone). We buy strength, not exhaustion.
        3. KELTNER -> 'Volatility Compression': Removed channel deviations. 
           Added a volatility clamp to reject entries during extreme expansion (pump/dump).
        """
        # Capital & Risk
        self.capital = 10000.0
        self.max_positions = 5
        self.position_size = self.capital / self.max_positions
        
        self.stop_loss_pct = 0.035       # 3.5% Hard Stop
        self.take_profit_pct = 0.075     # 7.5% Target
        self.trailing_arm_pct = 0.025    # Arm trailing stop after 2.5% gain
        self.trailing_gap_pct = 0.012    # 1.2% Trailing gap
        self.max_hold_ticks = 45         # Time-based exit
        
        # Filters
        self.min_liquidity = 600000.0
        self.min_vol_liq_ratio = 0.02
        
        # State
        self.history = {}
        self.positions = {}
        
        # EMA Settings (Fast for Trigger, Slow for Trend)
        self.ema_fast_period = 12
        self.ema_slow_period = 50
        self.fast_alpha = 2.0 / (self.ema_fast_period + 1)
        self.slow_alpha = 2.0 / (self.ema_slow_period + 1)

    def on_price_update(self, prices):
        # 1. Garbage Collection
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # 2. Position Management
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            # Update High Water Mark
            if curr_price > pos['high_price']:
                pos['high_price'] = curr_price
            
            roi = (curr_price - entry_price)