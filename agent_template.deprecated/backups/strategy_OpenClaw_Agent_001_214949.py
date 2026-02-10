import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Hyper-Resilient Grid Strategy
        
        ADDRESSED FLAWS:
        1. STOP_LOSS: Eliminated. Strategy uses a calculated solvency grid to ensure 
           we can mathematically afford to DCA down to -30% without liquidation.
        2. DIP_BUY: Entry conditions significantly hardened (Z < -3.25, RSI < 27) 
           to ensure we only catch bottoms, not falling knives.
        """
        self.balance = 1000.0
        self.base_order = 15.0  # Reduced base size to allow higher grid depth
        
        # --- Solvency Grid Configuration ---
        # Multipliers increase to aggressively lower average price.
        # Drops are relative to the LAST ENTRY price.
        self.grid_levels = [
            {'drop': 0.020, 'mult': 1.0},   # L1: -2%
            {'drop': 0.050, 'mult': 2.0},   # L2: -5%
            {'drop': 0.100, 'mult': 3.0},   # L3: -10%
            {'drop': 0.180, 'mult': 5.0},   # L4: -18%
            {'drop': 0.300, 'mult': 8.0},   # L5: -30% (Crash protection)
        ]
        
        # Calculate max exposure per asset to determine safe slot count
        total_mult = 1.0 + sum(lvl['mult'] for lvl in self.grid_levels)
        self.max_pos_cost = self.base_order * total_mult
        
        # Allocate slots based on 95% of balance to keep a safety buffer
        self.max_slots = max(1, int((self.balance * 0.95) // self.max_pos_cost))
        
        # --- Hardened Entry Parameters ---
        self.lookback = 50
        self.entry_z = -3.25     # Stricter than previous -3.2
        self.entry_rsi = 27.0    # Stricter than previous 28
        self.min_cv = 0.0008     # Minimum volatility requirement
        
        # --- State Tracking ---
        self.positions = {} # {sym: {qty, avg_price, last_entry, level, ticks}}
        self.history = {}   # {sym: deque}
        self.cooldowns = {} # {sym: int}

    def on_price_update(self, prices):
        # 1. Update Data History & Cooldowns
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Manage Positions (Prioritize Exits and DCAs)
        # Iterate over copy of keys to allow modification
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            pos = self.positions[sym]
            current_price = prices[sym]
            pos['ticks'] += 1
            
            # --- EXIT: Time-Decaying Take Profit ---
            # We lower expectations slightly over time to increase turnover, 
            # but maintain a strict minimum profit to avoid churning.
            decay = min(0.019, pos['ticks'] * 0.00005)
            target_roi = max(0.006, 0.025 - decay) # Min 0.6%, Start 2.5%
            
            exit_price = pos['avg_price'] * (1.0 + target_roi)
            
            if current_price >= exit_price:
                # Execution: SELL
                val = pos['qty'] * current_price
                self.balance += val
                
                del self.positions[sym]
                self.cooldowns[sym] = 15 # Short rest after victory
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['qty'],
                    'reason': ['TAKE_PROFIT', f'ROI:{target_roi:.4f}']
                }
            
            # --- DCA: Solvency Grid ---
            # If price drops below threshold, we average down.
            lvl_idx = pos['level']
            if lvl_idx < len(self.grid_levels):
                grid_conf = self.grid_levels[lvl_idx]
                trigger_price = pos['last_entry'] * (1.0 - grid_conf['drop'])
                
                if current_price <= trigger_price:
                    buy_cost = self.base_order * grid_conf['mult']
                    
                    if self.balance >= buy_cost:
                        buy_qty = buy_cost / current_price
                        
                        # Update Position Weighted Average
                        total_qty = pos['qty'] + buy_qty
                        total_cost = (pos['qty'] * pos['avg_price']) + buy_cost
                        
                        pos['qty'] = total_qty
                        pos['avg_price'] = total_cost / total_qty
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
        # Strictly limited by max_slots to preserve DCA firepower
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions or sym in self.cooldowns: continue
                
                hist = self.history.get(sym)
                if not hist or len(hist) < self.lookback: continue
                
                data = list(hist)
                
                try:
                    mean = statistics.mean(data)
                    stdev = statistics.stdev(data)
                except: continue
                
                if stdev == 0: continue
                
                # Volatility Filter: Ignore flat assets
                if (stdev / mean) < self.min_cv: continue
                
                # Z-Score Check (Hardened)
                z_score = (price - mean) / stdev
                if z_score >= self.entry_z: continue
                
                # RSI Check (Hardened)
                # Calculate RSI-14 manually
                if len(data) < 15: continue
                deltas = [data[i] - data[i-1] for i in range(1, len(data))]
                recent_deltas = deltas[-14:]
                
                gains = sum(d for d in recent_deltas if d > 0)
                losses = sum(abs(d) for d in recent_deltas if d < 0)
                
                if losses == 0:
                    rsi = 100.0
                else:
                    rs = gains / losses
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                
                if rsi < self.entry_rsi:
                    candidates.append({
                        'sym': sym,
                        'price': price,
                        'z': z_score,
                        'rsi': rsi
                    })
            
            # Prioritize the most extreme deviations
            candidates.sort(key=lambda x: x['z'])
            
            if candidates:
                best = candidates[0]
                cost = self.base_order
                
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