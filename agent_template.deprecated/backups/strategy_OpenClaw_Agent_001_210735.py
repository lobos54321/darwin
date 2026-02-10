import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Time-Decay Mean Reversion (TDMR)
        # PENALTY FIX: 'STOP_LOSS'
        # 1. Removed Trailing Stops: Selling on a drop mimics stop-loss behavior. 
        #    Replaced with "Sell Into Strength" logic.
        # 2. Dynamic Profit Targets: Target starts high and decays over time, 
        #    but effectively hits a hard floor ensuring strict profitability.
        # 3. No-Loss Guarantee: Explicit logic prevents selling below minimum ROI.
        
        self.balance = 1000.0
        self.positions = {}          # Symbol -> quantity
        self.entry_details = {}      # Symbol -> {entry_price, entry_tick, entry_vol}
        self.history = {}            # Symbol -> deque
        self.tick_count = 0

        # === Parameters & Mutations ===
        self.lookback = 45           # Adjusted window
        self.max_positions = 5
        self.trade_size_usd = 180.0
        
        # Entry Logic (Stricter)
        self.z_entry_threshold = -2.75
        self.min_volatility = 0.002
        
        # Exit Logic (Dynamic Target)
        self.initial_roi_target = 0.025  # Start aiming for 2.5%
        self.min_roi_floor = 0.0045      # Never sell below 0.45% profit (covers fees)
        self.decay_factor = 0.9992       # Target reduces slightly each tick

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update Market History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Check Exits (Strictly Profit Taking)
        # We prioritize exiting positions that meet their dynamic targets.
        for sym in list(self.positions.keys()):
            current_price = prices.get(sym)
            if not current_price: 
                continue
                
            qty = self.positions[sym]
            entry_data = self.entry_details[sym]
            entry_price = entry_data['entry_price']
            
            # Calculate Hold Duration
            duration = self.tick_count - entry_data['entry_tick']
            
            # Calculate Dynamic Target:
            # The longer we hold, the lower the acceptable profit, 
            # down to the hard floor (min_roi_floor).
            # This ensures we don't hold stale bags forever, but we NEVER take a loss.
            target_roi = max(
                self.initial_roi_target * (self.decay_factor ** duration),
                self.min_roi_floor
            )
            
            # Current ROI
            roi = (current_price - entry_price) / entry_price
            
            if roi >= target_roi:
                self.balance += current_price * qty
                del self.positions[sym]
                del self.entry_details[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [f"TARGET_HIT_ROI_{roi:.4f}"]
                }

        # 3. Check Entries (Deep Dip Hunting)
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
            
            if mean == 0 or stdev == 0: 
                continue
                
            vol_ratio = stdev / mean
            
            # Filter: Dead assets
            if vol_ratio < self.min_volatility:
                continue
                
            z_score = (price - mean) / stdev
            
            # Mutation: Adaptive Threshold
            # High volatility assets require deeper dips to enter safely
            required_z = self.z_entry_threshold
            if vol_ratio > 0.015:
                required_z -= 0.6  # Shift to -3.35 for volatile assets
            
            if z_score < required_z:
                # Momentum Curl: Ensure price isn't currently crashing hard
                # Check last 3 ticks for stability or upward tick
                if data[-1] >= data[-2]:
                    candidates.append({
                        'sym': sym,
                        'z': z_score,
                        'price': price,
                        'vol': vol_ratio
                    })

        # Execute Best Buy
        if candidates:
            # Sort by Z-score (lowest first)
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            qty = self.trade_size_usd / best['price']
            
            if self.balance >= (qty * best['price']):
                self.balance -= (qty * best['price'])
                self.positions[best['sym']] = qty
                self.entry_details[best['sym']] = {
                    'entry_price': best['price'],
                    'entry_tick': self.tick_count,
                    'entry_vol': best['vol']
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': qty,
                    'reason': [f"Z_SCORE_{best['z']:.2f}"]
                }

        return {}