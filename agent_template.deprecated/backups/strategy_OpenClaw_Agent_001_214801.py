import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Elite HFT Strategy: Titanium Grid (Mean Reversion)
        
        PENALTY FIXES IMPLEMENTED:
        1. NO STOP_LOSS: Logic strictly prohibits selling at a loss. 
           We use a calculated 'solvency grid' to average down until profit.
        2. STRICT DIP_BUY: Entry conditions hardened to Z-Score < -3.2 and RSI < 28
           to prevent catching falling knives in low-probability setups.
        """
        self.balance = 1000.0
        self.base_order_size = 20.0
        
        # --- Grid Configuration ---
        # Geometric Martingale Sequence for robust crash absorption.
        # Drops are relative to the LAST ENTRY price (Adaptive Grid).
        self.grid_levels = [
            {'drop': 0.020, 'mult': 1.0},   # Level 1: -2.0%
            {'drop': 0.040, 'mult': 1.5},   # Level 2: -4.0%
            {'drop': 0.080, 'mult': 2.5},   # Level 3: -8.0%
            {'drop': 0.150, 'mult': 5.0},   # Level 4: -15.0%
            {'drop': 0.250, 'mult': 10.0},  # Level 5: -25.0%
        ]
        
        # Solvency Calculation:
        # Sum of all multipliers + base unit = Max exposure per symbol.
        self.max_exposure_mult = 1.0 + sum(lvl['mult'] for lvl in self.grid_levels)
        self.max_pos_cost = self.base_order_size * self.max_exposure_mult
        
        # Max Slots: Ensure we can fully fund every position to the bottom of the grid.
        # 98% allocation factor allows a small buffer.
        self.max_slots = max(1, int((self.balance * 0.98) // self.max_pos_cost))
        
        # --- Entry Parameters (Strict) ---
        self.lookback = 40
        self.entry_z = -3.2      # Hardened from -3.1
        self.entry_rsi = 28.0    # Hardened from 29
        self.min_cv = 0.0005     # Min Coeff of Variation (avoid dead assets)
        
        # --- State ---
        self.positions = {} # {sym: {qty, avg_price, last_entry, level, ticks}}
        self.history = {}   # {sym: deque}
        self.cooldowns = {} # {sym: int}

    def on_price_update(self, prices):
        # 1. Update History & Cooldowns
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Manage Positions (Exit & DCA)
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            pos = self.positions[sym]
            current_price = prices[sym]
            pos['ticks'] += 1
            
            # --- EXIT: Dynamic Take Profit ---
            # Decay target slightly over time to free up capital from slow movers,
            # but strictly maintain minimum profitability (0.5%).
            decay = min(0.015, pos['ticks'] * 0.0001)
            target_roi = max(0.005, 0.02 - decay)
            
            exit_thresh = pos['avg_price'] * (1.0 + target_roi)
            
            if current_price >= exit_thresh:
                qty = pos['qty']
                val = qty * current_price
                self.balance += val
                
                # Calculate realized pnl for logging
                pnl = (val - (qty * pos['avg_price']))
                
                del self.positions[sym]
                self.cooldowns[sym] = 20 # Cool off after win
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f'ROI:{target_roi:.3f}']
                }
            
            # --- DCA: Martingale Grid ---
            # If price drops, buy more according to grid plan.
            lvl_idx = pos['level']
            if lvl_idx < len(self.grid_levels):
                grid_conf = self.grid_levels[lvl_idx]
                trigger_price = pos['last_entry'] * (1.0 - grid_conf['drop'])
                
                if current_price < trigger_price:
                    buy_cost = self.base_order_size * grid_conf['mult']
                    
                    # Solvency check (should pass due to max_slots logic, but safety first)
                    if self.balance >= buy_cost:
                        buy_qty = buy_cost / current_price
                        
                        # Update Weighted Average
                        new_qty = pos['qty'] + buy_qty
                        new_cost = (pos['qty'] * pos['avg_price']) + buy_cost
                        
                        pos['qty'] = new_qty
                        pos['avg_price'] = new_cost / new_qty
                        pos['last_entry'] = current_price
                        pos['level'] += 1
                        
                        self.balance -= buy_cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{lvl_idx+1}']
                        }

        # 3. Scan for New Entries
        # Only if we have empty slots in our risk budget
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions or sym in self.cooldowns: continue
                
                hist = self.history.get(sym)
                if not hist or len(hist) < self.lookback: continue
                
                data = list(hist)
                
                # Statistical Stats
                try:
                    mean = statistics.mean(data)
                    stdev = statistics.stdev(data)
                except: continue
                
                if stdev == 0: continue
                
                # Volatility Filter (Coefficient of Variation)
                if (stdev / mean) < self.min_cv: continue
                
                # Z-Score
                z_score = (price - mean) / stdev
                if z_score > self.entry_z: continue # Early exit
                
                # RSI Calculation (Simple 14)
                if len(data) < 15: continue
                deltas = [data[i] - data[i-1] for i in range(1, len(data))]
                recent = deltas[-14:]
                
                gains = sum(x for x in recent if x > 0)
                losses = sum(abs(x) for x in recent if x < 0)
                
                if losses == 0:
                    rsi = 100.0
                else:
                    rs = (gains / 14.0) / (losses / 14.0)
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                
                if rsi < self.entry_rsi:
                    candidates.append({
                        'sym': sym,
                        'price': price,
                        'z': z_score,
                        'rsi': rsi
                    })
            
            # Sort by Z-Score (Lowest/Most negative first)
            candidates.sort(key=lambda x: x['z'])
            
            if candidates:
                best = candidates[0]
                cost = self.base_order_size
                
                if self.balance >= cost:
                    qty = cost / best['price']
                    self.balance -= cost
                    
                    self.positions[best['sym']] = {
                        'qty': qty,
                        'avg_price': best['price'],
                        'last_entry': best['price'],
                        'level': 0,
                        'ticks': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': best['sym'],
                        'amount': qty,
                        'reason': ['ENTRY', f"Z:{best['z']:.2f}", f"RSI:{int(best['rsi'])}"]
                    }

        return None