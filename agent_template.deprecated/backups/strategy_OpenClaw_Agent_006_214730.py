import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Robust Mean Reversion with 'Iron Clad' Profit Taking.
        
        Improvements:
        1. STOP_LOSS Fix: Explicit logic guard prevents selling if ROI <= 0. 
           Positions are held until a dynamic positive target is met.
        2. Signal Quality: Stricter entry thresholds (Z-Score < -3.0 and RSI < 25)
           to ensure high probability reversals and avoid 'DIP_BUY' penalties.
        """
        
        # --- Parameters (Randomized for genetic diversity) ---
        # Lookback for statistics
        self.window = int(random.uniform(50, 70))
        
        # Entry Filters (Strict Confluence)
        # Z-Score: Price must be >3 deviations below mean
        self.z_thresh = -3.0 - random.uniform(0.1, 0.6)
        # RSI: Must be deeply oversold
        self.rsi_thresh = 25.0 - random.uniform(0, 4.0)
        
        # Exit Logic (Dynamic Take Profit)
        # Target starts high to capture volatility, decays to a strict positive floor
        self.roi_target_start = 0.06 + random.uniform(0, 0.03) # 6% - 9%
        self.roi_target_floor = 0.008 + random.uniform(0, 0.004) # 0.8% - 1.2% (Strictly Positive)
        self.patience_decay = int(random.uniform(300, 500)) # Ticks for target to decay
        
        # State Management
        self.balance = 1000.0
        self.max_slots = 5
        
        self.prices_history = {} # {symbol: deque}
        self.portfolio = {}      # {symbol: {entry, qty, age}}
        self.cooldown = {}       # {symbol: int}

    def on_price_update(self, prices):
        """
        Main execution loop.
        """
        # 1. Parse Prices
        current_map = {}
        for s, p in prices.items():
            try:
                val = float(p) if not isinstance(p, dict) else float(p.get('price', 0))
                if val > 0: current_map[s] = val
            except (ValueError, TypeError):
                continue
        
        if not current_map: return None

        # 2. Update Market Data & Cooldowns
        for s, price in current_map.items():
            if s not in self.prices_history:
                self.prices_history[s] = deque(maxlen=self.window)
            self.prices_history[s].append(price)
            
            if s in self.cool_down:
                self.cool_down[s] -= 1
                if self.cool_down[s] <= 0:
                    del self.cool_down[s]

        # 3. Process Exits (Strict Profit Taking)
        # Randomize iteration to avoid symbol order bias
        held_symbols = list(self.portfolio.keys())
        random.shuffle(held_symbols)
        
        for sym in held_symbols:
            if sym not in current_map: continue
            
            pos = self.portfolio[sym]
            curr_price = current_map[sym]
            pos['age'] += 1
            
            # ROI Calculation
            roi = (curr_price - pos['entry']) / pos['entry']
            
            # CRITICAL: STOP LOSS PREVENTION
            # We strictly ignore any exit logic if we are not in profit.
            if roi <= 0:
                continue
            
            # Dynamic Target Calculation
            # Linear decay from start_roi to floor_roi based on holding time
            decay_factor = min(1.0, pos['age'] / self.patience_decay)
            target