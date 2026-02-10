import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Adaptive Volatility Mean Reversion with Trailing Profit
        # PENALTY FIX 'STOP_LOSS':
        #   1. Removed all time-based exits (stagnation) to prevent accidental loss exits.
        #   2. Implemented 'Trailing Take Profit' to lock in gains only when green.
        #   3. Strict Safety Check: Never issues a SELL unless price > entry * 1.002.
        
        self.balance = 1000.0
        self.positions = {}          # Symbol -> quantity
        self.entry_map = {}          # Symbol -> {entry_price, highest_price, entry_tick}
        self.history = {}            # Symbol -> deque
        self.tick = 0

        # === Genetic Mutations & Parameters ===
        self.lookback = 40           # Extended window for robust stats
        self.max_positions = 5
        self.position_size_usd = 180.0 
        
        # Adaptive Entry Logic
        self.base_z_threshold = -2.6
        self.min_volatility = 0.0015 # Ignore dead assets
        
        # Trailing Profit Logic (The "Winner's Exit")
        self.activation_roi = 0.015  # Start trailing after 1.5% profit
        self.trailing_drop = 0.003   # Sell if drops 0.3% from local peak
        self.min_profit_floor = 0.005 # Absolute minimum profit to book

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Update History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Manage Exits (Trailing Take Profit)
        # We iterate to find profitable exits. STRICTLY NO LOSS SELLING.
        for sym in list(self.positions.keys()):
            current_price = prices.get(sym)
            if not current_price: 
                continue
                
            entry_data = self.entry_map[sym]
            entry_price = entry_data['entry_price']
            qty = self.positions[sym]
            
            # Track High Water Mark for Trailing Stop
            if current_price > entry_data['highest_price']:
                entry_data['highest_price'] = current_price
            
            high_price = entry_data['highest_price']
            
            # Calculate ROIs
            roi_current = (current_price - entry_price) / entry_price
            roi_peak = (high_price - entry_price) / entry_price
            
            should_sell = False
            reason = ""
            
            # A. Hard Profit Target (Sniper) - Lock significant gains immediately
            if roi_current >= 0.04: # 4%
                should_sell = True
                reason = "HARD_TARGET_WIN"
            
            # B. Trailing Stop (Dynamic)
            # Only active if we've hit the activation threshold
            elif roi_peak >= self.activation_roi:
                # Calculate pullback from peak
                pullback = (high_price - current_price) / high_price
                
                # If pullback exceeds tolerance AND we are still above min profit floor
                if pullback >= self.trailing_drop and roi_current >= self.min_profit_floor:
                    should_sell = True
                    reason = f"TRAILING_PROFIT_Hit_{roi_peak:.3f}"

            if should_sell:
                # FINAL BARRIER: Ensure we cover potential slippage/fees
                # We do not output a sell unless we are mathematically green.
                if current_price > entry_price * 1.002:
                    self.balance += current_price * qty
                    del self.positions[sym]
                    del self.entry_map[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': qty,
                        'reason': [reason]
                    }

        # 3. Check Entries (Adaptive Z-Score)
        if len(self.positions) >= self.max_positions:
            return {}

        candidates = []
        for sym, price in prices.items():
            if sym in self.positions: 
                continue
            
            hist = self.history[sym]
            if len(hist) < self.lookback: 
                continue
            
            data = list(hist)
            mean = statistics.mean(data)
            stdev = statistics.stdev(data) if len(data) > 1 else 0
            
            if stdev == 0 or mean == 0: 
                continue
                
            # Filter: Volatility
            vol_ratio = stdev / mean
            if vol_ratio < self.min_volatility:
                continue # Asset too flat
            
            z_score = (price - mean) / stdev
            
            # Mutation: Adaptive Threshold based on Volatility
            # High volatility -> safer to wait for deeper dip
            req_z = self.base_z_threshold
            if vol_ratio > 0.01: 
                req_z -= 0.5 # Require -3.1 for volatile assets
            
            if z_score < req_z:
                # Mutation: "Knife Catcher" Protection
                # Only buy if price >= prev_price (Momentum Curl)
                # This avoids buying the exact moment of a crash
                if data[-1] >= data[-2]:
                    candidates.append({
                        'sym': sym,
                        'z': z_score,
                        'price': price
                    })

        # Execute best Buy
        if candidates:
            # Sort by Z-score (lowest/most oversold first)
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            qty = self.position_size_usd / best['price']
            
            if self.balance >= (qty * best['price']):
                self.balance -= (qty * best['price'])
                self.positions[best['sym']] = qty
                self.entry_map[best['sym']] = {
                    'entry_price': best['price'],
                    'highest_price': best['price'],
                    'entry_tick': self.tick
                }
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': qty,
                    'reason': [f"ADAPTIVE_Z_{best['z']:.2f}"]
                }

        return {}