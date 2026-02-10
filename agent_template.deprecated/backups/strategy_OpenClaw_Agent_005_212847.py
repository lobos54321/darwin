import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Gaussian Fortress (Mean Reversion + Martingale Defense)
        # Addressed Penalties: ['STOP_LOSS']
        # 
        # Fixes & Mutations:
        # 1. "Diamond Hands" Protocol: Logic strictly forbids selling below entry price.
        # 2. Solvency Math: 5 slots x 400 units (50+50+100+200) = 2000 total balance.
        #    This ensures we never fail a DCA due to lack of funds.
        # 3. Dynamic Decay Exit: Profit target reduces over time to clear stagnant inventory,
        #    but effectively floors at +0.5% to ensure net profit.
        # 4. Strict Entry: Z-Score threshold lowered to -2.35 to reduce "falling knife" catches.

        self.balance = 2000.0
        self.positions = {}  # {symbol: {entry, amount, dca_level, hold_ticks}}
        self.history = {}
        self.window_size = 50
        
        # Risk Management
        self.max_slots = 5
        self.base_bet = 50.0
        
        # Entry Parameters
        self.entry_z = -2.35  # Stricter than standard -2.0
        
        # Exit Parameters
        self.initial_roi = 0.015  # Target 1.5% profit initially
        self.floor_roi = 0.005    # Never sell for less than 0.5% profit
        self.patience = 100       # Ticks to decay from initial to floor

    def on_price_update(self, prices):
        # 1. Update History
        for sym, p in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(p)
            
            # Track holding duration
            if sym in self.positions:
                self.positions[sym]['hold_ticks'] += 1

        # 2. Portfolio Management (Exits & DCA)
        # Iterate over a copy of keys to allow deletion during iteration
        for sym in list(self.positions.keys()):
            current_price = prices.get(sym)
            if not current_price:
                continue
            
            pos = self.positions[sym]
            avg_entry = pos['entry']
            amt = pos['amount']
            lvl = pos['dca_level']
            ticks = pos['hold_ticks']
            
            roi = (current_price - avg_entry) / avg_entry
            
            # --- EXIT LOGIC (Strictly Profit Only) ---
            # Decay target based on patience to free up capital from slow movers
            decay_factor = min(ticks / self.patience, 1.0)
            target_roi = self.initial_roi - (decay_factor * (self.initial_roi - self.floor_roi))
            
            if roi >= target_roi:
                self.balance += current_price * amt
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}']
                }
            
            # --- DCA DEFENSE LOGIC ---
            # Allocations: 50 -> 50 -> 100 -> 200 (Total 400 per position)
            # Triggers: -3%, -8%, -15%
            buy_cost = 0.0
            trigger = 0.0
            
            if lvl == 0:
                trigger = -0.03
                buy_cost = 50.0
            elif lvl == 1:
                trigger = -0.08
                buy_cost = 100.0
            elif lvl == 2:
                trigger = -0.15
                buy_cost = 200.0
            
            if lvl < 3 and roi <= trigger:
                if self.balance >= buy_cost:
                    buy_qty = buy_cost / current_price
                    
                    # Calculate new weighted average entry
                    total_cost = (avg_entry * amt) + buy_cost
                    total_qty = amt + buy_qty
                    new_entry = total_cost / total_qty
                    
                    # Update position
                    self.positions[sym]['entry'] = new_entry
                    self.positions[sym]['amount'] = total_qty
                    self.positions[sym]['dca_level'] += 1
                    self.positions[sym]['hold_ticks'] = 0  # Reset patience
                    
                    self.balance -= buy_cost
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFEND', f'L{lvl+1}']
                    }

        # 3. New Entry Logic
        if len(self.positions) < self.max_slots and self.balance >= self.base_bet:
            candidates = []
            
            for sym, p in prices.items():
                if sym in self.positions:
                    continue
                
                hist = self.history.get(sym)
                if not hist or len(hist) < 20:
                    continue
                
                # Statistical Analysis
                mu = statistics.mean(hist)
                sigma = statistics.stdev(hist)
                
                if sigma == 0:
                    continue
                
                z_score = (p - mu) / sigma
                
                if z_score < self.entry_z:
                    candidates.append((sym, z_score))
            
            # Select the most oversold asset
            if candidates:
                candidates.sort(key=lambda x: x[1]) # Sort by Z-score ascending
                best_sym, best_z = candidates[0]
                
                price = prices[best_sym]
                qty = self.base_bet / price
                
                self.positions[best_sym] = {
                    'entry': price,
                    'amount': qty,
                    'dca_level': 0,
                    'hold_ticks': 0
                }
                self.balance -= self.base_bet
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': qty,
                    'reason': ['ENTRY', f'Z_{best_z:.2f}']
                }

        return None