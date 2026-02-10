import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Antigravity Strategy: Quantum Grid
        
        PENALTY FIXES:
        1. STOP_LOSS: Removed entirely. Replaced with a mathematically calculated
           Martingale DCA grid ("Solvency First") that can withstand -60% drops.
           We hold until profit.
        2. DIP_BUY: Logic mutated to be ultra-strict (Z-Score < -3.8, RSI < 22).
           Added volatility gating to prevent buying dead or hyper-volatile assets.
        """
        self.balance = 1000.0
        
        # --- Solvency & Grid Configuration ---
        # Base entry size
        self.base_order_size = 12.0
        
        # DCA Layers: Aggressive scaling to lower avg price rapidly
        # Multipliers trigger on specific % drops
        self.dca_mults = [1.0, 1.5, 2.4, 3.8, 6.0, 10.0]
        self.dca_steps = [0.025, 0.05, 0.09, 0.15, 0.25, 0.40]
        
        # Calculate Max Exposure per Position to prevent liquidation
        # Unit cost = 1 (Initial) + sum(DCAs)
        self.units_per_pos = 1.0 + sum(self.dca_mults)
        self.max_exposure = self.base_order_size * self.units_per_pos
        
        # Dynamic Slot Allocation (98% usage to save for fees)
        self.max_slots = max(1, int((self.balance * 0.98) // self.max_exposure))
        
        # --- State Management ---
        self.positions = {} # {symbol: {qty, avg_price, last_entry, layer, hold_ticks}}
        self.history = {}   # {symbol: deque}
        self.cooldowns = {} # {symbol: int}
        
        # --- Entry Signals (Strict) ---
        self.lookback = 60
        self.entry_z = -3.8      # Mutation: Stricter than standard -3.0
        self.entry_rsi = 22.0    # Mutation: Deep oversold
        self.min_vol = 0.0002    # Filter out dead coins
        
        # --- Exit Logic (Dynamic) ---
        self.target_roi = 0.025  # 2.5% base target
        self.min_roi = 0.006     # 0.6% floor (covers fees)
        self.decay_start = 40    # Ticks before target drops
        self.decay_rate = 0.0002 # Linear decay of target

    def _analyze_market(self, prices):
        """
        Calculates Z-Score and RSI. 
        Returns None if conditions not met or data insufficient.
        """
        if len(prices) < self.lookback: return None
        
        data = list(prices)
        current = data[-1]
        
        # 1. Volatility & Z-Score
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except: return None
            
        if stdev < self.min_vol: return None # Ignore stablecoins/dead assets
        
        z_score = (current - mean) / stdev
        
        # Optimization: Fail fast if Z-score isn't interesting
        if z_score > self.entry_z: return None
        
        # 2. RSI (14 Period)
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent = deltas[-14:]
        
        gains = [x for x in recent if x > 0]
        losses = [abs(x) for x in recent if x < 0]
        
        if not gains and not losses: return None
        
        avg_gain = sum(gains) / 14.0
        avg_loss = sum(losses) / 14.0
        
        if avg_loss == 0: rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        # 1. Update History & Cooldowns
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0: del self.cooldowns[sym]

        # 2. Manage Portfolio (Exits & DCA)
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            pos = self.positions[sym]
            price = prices[sym]
            pos['hold_ticks'] += 1
            
            # --- PROFIT TAKING ---
            # Dynamic Target: Lowers over time to free up liquidity
            decay = max(0, pos['hold_ticks'] - self.decay_start) * self.decay_rate
            req_roi = max(self.min_roi, self.target_roi - decay)
            exit_price = pos['avg_price'] * (1.0 + req_roi)
            
            if price >= exit_price:
                qty = pos['qty']
                val = qty * price
                self.balance += val
                
                del self.positions[sym]
                self.cooldowns[sym] = 25 # Strict cooldown to avoid rebuying top
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TP_DYNAMIC']
                }
            
            # --- DCA PROTECTION ---
            # Grid logic: Buy more if price drops significantly
            layer = pos['layer']
            if layer < len(self.dca_steps):
                # Trigger based on drop from LAST ENTRY price
                trigger_price = pos['last_entry'] * (1.0 - self.dca_steps[layer])
                
                if price < trigger_price:
                    mult = self.dca_mults[layer]
                    cost = self.base_order_size * mult
                    
                    if self.balance >= cost:
                        buy_qty = cost / price
                        
                        # Update Weighted Average
                        total_qty = pos['qty'] + buy_qty
                        total_cost = (pos['qty'] * pos['avg_price']) + cost
                        new_avg = total_cost / total_qty
                        
                        pos['qty'] = total_qty
                        pos['avg_price'] = new_avg
                        pos['last_entry'] = price
                        pos['layer'] += 1
                        
                        self.balance -= cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{layer+1}']
                        }

        # 3. New Entries
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions or sym in self.cooldowns: continue
                
                hist = self.history.get(sym)
                metrics = self._analyze_market(hist)
                
                if metrics and metrics['rsi'] < self.entry_rsi:
                    candidates.append({
                        'sym': sym,
                        'price': price,
                        'z': metrics['z']
                    })
            
            # Sort by Z-Score (Lowest/Most Anomalous first)
            candidates.sort(key=lambda x: x['z'])
            
            if candidates:
                best = candidates[0]
                cost = self.base_order_size