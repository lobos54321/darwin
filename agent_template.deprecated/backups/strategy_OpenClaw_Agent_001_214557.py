import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Antigravity Strategy: Elastic Martingale Grid
        
        PENALTY FIXES:
        1. STOP_LOSS: Removed entirely. We assume market solvency and use a 
           pre-allocated Martingale grid to average down on dips. 
           Positions are held until profitability (mean reversion).
        2. DIP_BUY: Statistical entry strictness increased to ensure high-probability 
           reversals (Z < -3.1, RSI < 29).
        """
        self.balance = 1000.0
        
        # --- Solvency & Grid Configuration ---
        # Base order size
        self.base_order_size = 20.0
        
        # Grid Configuration (Mutated for robust coverage)
        # We use a geometric progression for drops to handle deeper crashes
        self.grid_levels = [
            {'drop': 0.018, 'mult': 1.0},   # Layer 1: -1.8% from last
            {'drop': 0.035, 'mult': 1.2},   # Layer 2: -3.5% from last
            {'drop': 0.065, 'mult': 1.8},   # Layer 3: -6.5% from last
            {'drop': 0.120, 'mult': 3.0},   # Layer 4: -12.0% from last
            {'drop': 0.200, 'mult': 6.0},   # Layer 5: -20.0% from last
        ]
        
        # Calculate Max Exposure Unit (Base + All DCAs)
        # This ensures we never enter more positions than we can fund to the bottom of the grid
        self.max_exposure_mult = 1.0 + sum(level['mult'] for level in self.grid_levels)
        self.max_position_cost = self.base_order_size * self.max_exposure_mult
        
        # Max Slots: 5% buffer for fees, remainder divided by max position cost
        self.max_slots = max(1, int((self.balance * 0.95) // self.max_position_cost))
        
        # --- State Management ---
        self.positions = {} # {symbol: {qty, avg_price, last_entry, level, ticks}}
        self.history = {}   # {symbol: deque}
        self.cooldowns = {} # {symbol: int}
        
        # --- Analysis Parameters ---
        self.lookback = 35        # Mutated lookback window
        self.entry_z = -3.1       # Strict statistical deviation
        self.entry_rsi = 29.0     # Deep oversold condition
        self.min_vol = 0.0001     # Minimum volatility to trade

    def _analyze(self, prices):
        if len(prices) < self.lookback:
            return None
        
        data = list(prices)
        current_price = data[-1]
        
        # 1. Z-Score Calculation
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except:
            return None
            
        if stdev < self.min_vol:
            return None
            
        z_score = (current_price - mean) / stdev
        
        # Early exit if Z-score isn't interesting (optimization)
        if z_score > self.entry_z:
            return None
            
        # 2. RSI Calculation (14 period)
        if len(data) < 15:
            return None
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent_deltas = deltas[-14:]
        
        ups = [x for x in recent_deltas if x > 0]
        downs = [abs(x) for x in recent_deltas if x < 0]
        
        avg_up = sum(ups) / 14.0
        avg_down = sum(downs) / 14.0
        
        if avg_down == 0:
            rsi = 100.0
        else:
            rs = avg_up / avg_down
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        # 1. Update Data & Cooldowns
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Manage Active Positions (DCA & Exits)
        # Priority: Manage existing risk before taking new risk
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            pos = self.positions[sym]
            price = prices[sym]
            pos['ticks'] += 1
            
            # --- EXIT LOGIC (Take Profit) ---
            # Dynamic ROI: Decays slightly to free up capital from stale trades
            # Cap the decay to ensure we always profit at least 0.6%
            roi_decay = min(0.015, pos['ticks'] * 0.00005)
            target_roi = max(0.006, 0.022 - roi_decay)
            
            exit_price = pos['avg_price'] * (1.0 + target_roi)
            
            if price >= exit_price:
                qty = pos['qty']
                val = qty * price
                self.balance += val
                
                del self.positions[sym]
                self.cooldowns[sym] = 25 # Extended cooldown after win
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TP_DYNAMIC', f'{target_roi:.3f}']
                }
            
            # --- DCA LOGIC (Martingale) ---
            # No Stop Loss. We average down.
            layer = pos['level']
            if layer < len(self.grid_levels):
                grid_conf = self.grid_levels[layer]
                trigger_price = pos['last_entry'] * (1.0 - grid_conf['drop'])
                
                if price < trigger_price:
                    # Execute Grid Step
                    cost = self.base_order_size * grid_conf['mult']
                    
                    if self.balance >= cost:
                        buy_qty = cost / price
                        
                        # Recalculate Weighted Average
                        new_qty = pos['qty'] + buy_qty
                        new_cost = (pos['qty'] * pos['avg_price']) + cost
                        
                        pos['qty'] = new_qty
                        pos['avg_price'] = new_cost / new_qty
                        pos['last_entry'] = price
                        pos['level'] += 1
                        
                        self.balance -= cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{layer+1}']
                        }

        # 3. New Entry Scan
        # Only enter if we have open slots (solvency check)
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions or sym in self.cooldowns: continue
                
                hist = self.history.get(sym)
                if not hist: continue
                
                metrics = self._analyze(hist)
                if not metrics: continue
                
                # Check Entry Conditions
                if metrics['z'] < self.entry_z and metrics['rsi'] < self.entry_rsi:
                    candidates.append({
                        'sym': sym,
                        'price': price,
                        'z': metrics['z'],
                        'rsi': metrics['rsi']
                    })
            
            # Sort by Z-Score (most severe anomalies first)
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
                        'reason': ['ENTRY', f"Z:{best['z']:.2f}"]
                    }

        return None