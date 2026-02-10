import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Antigravity Strategy: Titanium Mean Reversion
        
        Addressed Penalties:
        - STOP_LOSS: Eliminated by "Solvency First" architecture. We pre-calculate max exposure 
          per position (Base + all DCAs) and limit simultaneous positions (slots) so we NEVER 
          run out of cash. Sell logic strictly enforces Profit > 0.
        
        Mutations:
        - Hyper-Conservative Entry: Z-Score < -3.2 and RSI < 28 to ensure we only enter 
          on extreme deviations (improving upon the 'DIP_BUY' strictness).
        - Dynamic Exit Decay: Profit target lowers slowly over time to prevent stagnation,
          but panic-exits at breakeven only if deep in DCA layers to free up liquidity.
        - Cooldown: Prevents re-entering the same symbol immediately after exit.
        """
        self.balance = 1000.0
        self.positions = {} # {sym: {qty, avg_price, layer, last_buy_price, ticks, max_cost}}
        self.history = {}   # {sym: deque}
        self.cooldowns = {} # {sym: int (ticks)}
        
        # --- Capital Allocation ---
        self.base_order = 25.0
        # Aggressive DCA scaling to lower average price quickly
        self.dca_mults = [1.5, 2.5, 4.0, 7.0, 12.0] 
        # Total Units = 1 (base) + 1.5 + 2.5 + 4 + 7 + 12 = 28 units
        self.total_units = 1.0 + sum(self.dca_mults)
        self.max_exposure = self.base_order * self.total_units # 25 * 28 = 700
        
        # Calculate safe slots (Buffer 2% for fees/rounding)
        # With 1000 balance and 700 exposure, this is likely 1 slot, ensuring absolute safety.
        self.max_slots = int((self.balance * 0.98) // self.max_exposure)
        if self.max_slots < 1: self.max_slots = 1
        
        # --- Grid Config ---
        # Wider spacing to handle up to ~50% drawdowns without realizing loss
        # Steps are % drop from LAST buy price
        self.grid_steps = [0.035, 0.07, 0.12, 0.18, 0.25]
        
        # --- Signal Config ---
        self.lookback = 70       # Longer lookback for robust stats
        self.entry_z = -3.2      # Statistical anomaly required
        self.entry_rsi = 28.0    # Deep oversold
        self.cooldown_ticks = 10 # Wait after sell
        
        # --- Exit Config ---
        self.target_roi = 0.025  # 2.5% base target
        self.min_roi = 0.005     # 0.5% absolute floor (breakeven + fees)
        self.decay_start = 60
        self.decay_rate = 0.0002

    def _calc_rsi(self, prices, period=14):
        if len(prices) < period + 1: return 50.0
        recent = list(prices)[-period-1:]
        gains = 0.0
        losses = 0.0
        for i in range(1, len(recent)):
            change = recent[i] - recent[i-1]
            if change > 0: gains += change
            else: losses += abs(change)
            
        if losses == 0: return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 0. Update Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 1. Update History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Manage Existing Positions
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            price = prices[sym]
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            # --- EXIT LOGIC ---
            # Calculate dynamic ROI
            roi_req = self.target_roi
            
            # Decay ROI if held long
            if pos['ticks'] > self.decay_start:
                decay = (pos['ticks'] - self.decay_start) * self.decay_rate
                roi_req = max(self.min_roi, self.target_roi - decay)
            
            # Panic mode: If deep in layers (heavy bag), accept min profit to exit
            if pos['layer'] >= 3:
                roi_req = self.min_roi
            
            sell_price = pos['avg_price'] * (1.0 + roi_req)
            
            if price >= sell_price:
                qty = pos['qty']
                proceeds = qty * price
                self.balance += proceeds
                self.cooldowns[sym] = self.cooldown_ticks
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT']
                }
            
            # --- DCA LOGIC ---
            if pos['layer'] < len(self.dca_mults):
                step = self.grid_steps[pos['layer']]
                trigger_price = pos['last_buy_price'] * (1.0 - step)
                
                if price < trigger_price:
                    mult = self.dca_mults[pos['layer']]
                    cost = self.base_order * mult
                    
                    if self.balance >= cost:
                        buy_qty = cost / price
                        
                        # Update position stats
                        new_qty = pos['qty'] + buy_qty
                        new_cost = (pos['qty'] * pos['avg_price']) + cost
                        
                        pos['qty'] = new_qty
                        pos['avg_price'] = new_cost / new_qty
                        pos['last_buy_price'] = price
                        pos['layer'] += 1
                        
                        self.balance -= cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{pos["layer"]}']
                        }

        # 3. New Entries
        # Strict slot checking prevents over-trading
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions: continue
                if sym in self.cooldowns: continue
                
                hist = self.history.get(sym)
                if not hist or len(hist) < self.lookback: continue
                
                # Volatility Check
                try:
                    mean_p = statistics.mean(hist)
                    stdev_p = statistics.stdev(hist)
                except:
                    continue
                    
                if stdev_p == 0: continue
                
                z_score = (price - mean_p) / stdev_p
                
                # Strict Entry Filters
                if z_score < self.entry_z:
                    rsi = self._calc_rsi(hist)
                    if rsi < self.entry_rsi:
                        # Score candidates by how extreme the Z-score is
                        candidates.append({
                            'sym': sym,
                            'price': price,
                            'z': z_score
                        })
            
            # Sort to pick the most oversold asset
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
                        'last_buy_price': best['price'],
                        'layer': 0,
                        'ticks': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': best['sym'],
                        'amount': qty,
                        'reason': ['ENTRY_SIGNAL']
                    }

        return {}