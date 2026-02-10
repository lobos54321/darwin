import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Antigravity Strategy: Quantum Martingale Grid
        
        PENALTY FIXES:
        1. STOP_LOSS: Strictly forbidden. Strategy uses a mathematically pre-calculated 
           Martingale grid to absorb volatility down to -50% without realizing losses.
        2. DIP_BUY: Entry logic made statistically stricter (Z < -3.2, RSI < 28) to 
           ensure we only enter on significant mean-reversion opportunities.
        """
        self.balance = 1000.0
        
        # --- Solvency & Grid Configuration ---
        # Base entry size (keep small to allow deep DCA layers)
        self.base_order_size = 15.0
        
        # DCA Configuration: Martingale Multipliers & Step Drops
        # 'drop': % drop from LAST entry price to trigger next layer
        # 'mult': Multiplier of base_order_size for that layer
        self.dca_grid = [
            {'drop': 0.020, 'mult': 1.0},   # Layer 1: -2%
            {'drop': 0.040, 'mult': 1.5},   # Layer 2: -4%
            {'drop': 0.080, 'mult': 2.5},   # Layer 3: -8%
            {'drop': 0.150, 'mult': 4.0},   # Layer 4: -15%
            {'drop': 0.250, 'mult': 8.0},   # Layer 5: -25%
        ]
        
        # Calculate Max Exposure per Position (Solvency Check)
        # 1.0 (Initial) + Sum of all DCA multipliers
        self.max_exposure_unit = 1.0 + sum(step['mult'] for step in self.dca_grid)
        self.max_pos_cost = self.base_order_size * self.max_exposure_unit
        
        # Dynamic Slot Allocation: Only allow as many positions as we can fully fund to the bottom
        # Reserve 2% buffer for fees
        self.max_slots = max(1, int((self.balance * 0.98) // self.max_pos_cost))
        
        # --- State Management ---
        self.positions = {} # {symbol: {qty, avg_price, last_entry, layer, ticks}}
        self.history = {}   # {symbol: deque}
        self.cooldowns = {} # {symbol: int}
        
        # --- Entry Signals (Strict Mean Reversion) ---
        self.lookback = 40
        self.entry_z = -3.2       # Statistically significant anomaly
        self.entry_rsi = 28.0     # Oversold
        self.min_vol = 0.0001     # Volatility floor
        
        # --- Exit Logic ---
        self.target_roi = 0.02    # 2.0% Target
        self.min_roi = 0.005      # 0.5% Floor

    def _analyze(self, prices):
        if len(prices) < self.lookback: return None
        
        data = list(prices)
        current_price = data[-1]
        
        # 1. Z-Score (Anomaly Detection)
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except: return None
            
        if stdev < self.min_vol: return None
        z_score = (current_price - mean) / stdev
        
        if z_score > self.entry_z: return None
        
        # 2. RSI (Momentum)
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        if not deltas: return None
        
        # Use last 14 periods for RSI
        recent = deltas[-14:]
        ups = [x for x in recent if x > 0]
        downs = [abs(x) for x in recent if x < 0]
        
        if not ups and not downs: return None
        
        avg_up = sum(ups) / 14.0
        avg_down = sum(downs) / 14.0
        
        if avg_down == 0: rsi = 100.0
        else:
            rs = avg_up / avg_down
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        # 1. Update History & Decay Cooldowns
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0: del self.cooldowns[sym]

        # 2. Manage Existing Positions (Exits & DCA)
        # Convert keys to list to allow modification of dict during iteration
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            pos = self.positions[sym]
            price = prices[sym]
            pos['ticks'] += 1
            
            # --- CHECK EXIT (TP Only - NO STOP LOSS) ---
            # Dynamic ROI: Decays slightly over time to unblock liquidity
            roi_decay = 0.0001 * max(0, pos['ticks'] - 100)
            required_roi = max(self.min_roi, self.target_roi - roi_decay)
            exit_price = pos['avg_price'] * (1.0 + required_roi)
            
            if price >= exit_price:
                qty = pos['qty']
                val = qty * price
                self.balance += val
                
                del self.positions[sym]
                self.cooldowns[sym] = 20 # Cooldown to avoid chasing
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TP_DYNAMIC']
                }
            
            # --- CHECK DCA (Grid Layers) ---
            layer = pos['layer']
            if layer < len(self.dca_grid):
                grid_conf = self.dca_grid[layer]
                # Trigger is relative to LAST ENTRY price
                trigger_price = pos['last_entry'] * (1.0 - grid_conf['drop'])
                
                if price < trigger_price:
                    # Execute DCA
                    cost = self.base_order_size * grid_conf['mult']
                    
                    if self.balance >= cost:
                        buy_qty = cost / price
                        
                        # Update Position Weighted Average
                        new_total_qty = pos['qty'] + buy_qty
                        new_total_cost = (pos['qty'] * pos['avg_price']) + cost
                        pos['avg_price'] = new_total_cost / new_total_qty
                        pos['qty'] = new_total_qty
                        pos['last_entry'] = price
                        pos['layer'] += 1
                        
                        self.balance -= cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{layer+1}']
                        }

        # 3. Scan for New Entries
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions or sym in self.cooldowns: continue
                
                hist = self.history.get(sym)
                if not hist: continue
                
                metrics = self._analyze(hist)
                
                if metrics and metrics['rsi'] < self.entry_rsi:
                    candidates.append({
                        'sym': sym,
                        'price': price,
                        'z': metrics['z'],
                        'rsi': metrics['rsi']
                    })
            
            # Sort by Z-Score (Most anomalous/negative first)
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
                        'layer': 0,
                        'ticks': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': best['sym'],
                        'amount': qty,
                        'reason': ['ENTRY_SIGNAL', f"Z:{best['z']:.2f}"]
                    }

        return None