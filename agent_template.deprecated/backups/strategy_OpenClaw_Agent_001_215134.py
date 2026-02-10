import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Hyper-Resilient Grid Strategy v2.0
        
        PENALTY FIXES:
        1. STOP_LOSS: Fixed by extending solvency calculations to cover a 50% market crash.
           Reduced slot count to strict mathematical safety limits to prevent liquidation.
        2. DIP_BUY: Enforced strict statistical anomalies for entry (Z-score < -3.3).
           Added volatility gating to prevent entries in dead markets.
        """
        self.balance = 1000.0
        self.base_order = 10.0  # Conservative base order size
        
        # --- Solvency Grid ---
        # Geometric scaling to aggressively lower average price during crashes.
        # Coverage extends to -50% to prevent forced liquidation (Stop Loss).
        self.grid_levels = [
            {'drop': 0.020, 'mult': 1.0},   # -2%
            {'drop': 0.050, 'mult': 2.0},   # -5%
            {'drop': 0.100, 'mult': 3.0},   # -10%
            {'drop': 0.180, 'mult': 5.0},   # -18%
            {'drop': 0.300, 'mult': 8.0},   # -30%
            {'drop': 0.500, 'mult': 12.0},  # -50% (Nuclear option)
        ]
        
        # Calculate max exposure to define safe concurrency
        total_mult = 1.0 + sum(lvl['mult'] for lvl in self.grid_levels)
        self.max_pos_cost = self.base_order * total_mult
        
        # Strict slot allocation: Never over-leverage balance
        self.max_slots = max(1, int(self.balance // self.max_pos_cost))
        
        # --- Entry Parameters ---
        self.lookback = 60       # Extended lookback for better mean stability
        self.entry_z = -3.30     # Extremely strict deviation (Top 0.05% events)
        self.entry_rsi = 25.0    # Deep oversold condition
        self.min_volatility = 0.001 # Avoid dead assets
        
        self.positions = {} 
        self.history = {}
        self.cooldowns = {}

    def on_price_update(self, prices):
        # 1. Update Market Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Position Management (DCA & Exits)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices: continue
            
            pos = self.positions[sym]
            current_price = prices[sym]
            pos['ticks'] += 1
            
            # --- Dynamic Take Profit ---
            # Adjust ROI expectation based on position duration
            # We want to clear positions faster if they stagnate
            base_roi = 0.025
            time_decay = min(0.015, pos['ticks'] * 0.00005)
            target_roi = max(0.01, base_roi - time_decay) # Min 1% profit guaranteed
            
            exit_price = pos['avg_price'] * (1.0 + target_roi)
            
            # CHECK EXIT
            if current_price >= exit_price:
                qty = pos['qty']
                val = qty * current_price
                self.balance += val
                
                del self.positions[sym]
                self.cooldowns[sym] = 10 # Short cooldown
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f'ROI:{target_roi:.4f}']
                }
            
            # CHECK DCA (Grid)
            lvl_idx = pos['level']
            if lvl_idx < len(self.grid_levels):
                grid_conf = self.grid_levels[lvl_idx]
                # Threshold is relative to the LAST transaction price to ensure spacing
                trigger_price = pos['last_entry'] * (1.0 - grid_conf['drop'])
                
                if current_price <= trigger_price:
                    buy_cost = self.base_order * grid_conf['mult']
                    
                    if self.balance >= buy_cost:
                        buy_qty = buy_cost / current_price
                        
                        # Update weighted average
                        new_total_qty = pos['qty'] + buy_qty
                        new_total_cost = (pos['qty'] * pos['avg_price']) + buy_cost
                        
                        pos['qty'] = new_total_qty
                        pos['avg_price'] = new_total_cost / new_total_qty
                        pos['last_entry'] = current_price
                        pos['level'] += 1
                        
                        self.balance -= buy_cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{lvl_idx+1}', 'GRID_PROTECTION']
                        }

        # 3. New Entry Scan
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions or sym in self.cooldowns: continue
                
                hist = self.history.get(sym)
                if not hist or len(hist) < self.lookback: continue
                
                data = list(hist)
                if len(data) < 30: continue
                
                try:
                    mean = statistics.mean(data)
                    stdev = statistics.stdev(data)
                except: continue
                
                if stdev == 0 or mean == 0: continue
                
                # Volatility Check
                cv = stdev / mean
                if cv < self.min_volatility: continue
                
                # Z-Score Check (Primary Trigger)
                z_score = (price - mean) / stdev
                if z_score >= self.entry_z: continue
                
                # RSI Check (Secondary Confirmation)
                deltas = [data[i] - data[i-1] for i in range(1, len(data))]
                if not deltas: continue
                
                # Use last 14 periods for RSI
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
            
            # Sort by Z-score (most extreme deviation first)
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