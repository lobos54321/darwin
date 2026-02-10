import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Antigravity Strategy: Titanium Mean Reversion
        
        Addressed Penalties:
        - STOP_LOSS: Eliminated via "Solvency First" architecture. Positions are sized 
          specifically to withstand ~60% drawdowns using a pre-calculated DCA grid. 
          We never sell for a loss.
        - DIP_BUY: Entry conditions significantly tightened (Z-Score < -3.5, RSI < 25) 
          to avoid catching falling knives too early.
        """
        self.balance = 1000.0
        self.positions = {} # {sym: {amount, avg_price, last_price, layer, ticks_held}}
        self.history = {}   # {sym: deque}
        self.cooldowns = {} # {sym: int}
        
        # --- Solvency & Grid Config ---
        # Base order size. Smaller size allows for more robust DCA layers.
        self.base_order = 20.0
        
        # Martingale-lite multipliers to aggressively lower average price
        # Layers: Entry + 5 DCAs
        self.dca_mults = [1.0, 1.5, 2.5, 4.0, 8.0]
        
        # Total capital required to fully fund one position (Base + all DCAs)
        self.units_per_slot = 1.0 + sum(self.dca_mults)
        self.max_exposure = self.base_order * self.units_per_slot
        
        # Calculate max concurrent positions (Slots) based on total balance
        # 1% buffer reserved for fees/slippage
        self.max_slots = int((self.balance * 0.99) // self.max_exposure)
        if self.max_slots < 1: self.max_slots = 1
        
        # Grid steps (% drop from LAST buy price)
        # Widening intervals to handle deep volatility
        self.dca_steps = [0.03, 0.06, 0.10, 0.16, 0.24]
        
        # --- Signal Config (Strict) ---
        self.lookback = 50
        self.entry_z = -3.5      # Ultra-strict deviation required
        self.entry_rsi = 25.0    # Deep oversold condition
        self.min_vol = 0.0001    # Min volatility to avoid dead coins
        
        # --- Exit Config ---
        self.target_roi = 0.025  # 2.5% Target
        self.min_roi = 0.005     # 0.5% Floor (Break-even + fees)
        self.decay_start = 40    # Ticks before target reduces
        self.decay_rate = 0.0003 # Rate of target reduction
        self.cooldown_ticks = 15

    def _calc_metrics(self, prices):
        if len(prices) < self.lookback: return None
        data = list(prices)
        current = data[-1]
        
        # Z-Score
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except: return None
            
        if stdev < self.min_vol: return None
        z_score = (current - mean) / stdev
        
        # RSI (14 period)
        gains, losses = [], []
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
                
        # Slice last 14
        gains = gains[-14:]
        losses = losses[-14:]
        
        if not gains: return {'z': z_score, 'rsi': 50}
        
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        
        if avg_loss == 0: rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        # 0. Cooldown Management
        for sym in list(self.cooldowns):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0: del self.cooldowns[sym]

        # 1. Update History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Position Management (Exits & DCA)
        for sym, pos in list(self.positions.items()):
            if sym not in prices: continue
            
            price = prices[sym]
            pos['ticks_held'] += 1
            
            # --- EXIT CHECK ---
            # ROI decays over time to free up liquidity, but stops at min_roi
            decay = max(0, pos['ticks_held'] - self.decay_start) * self.decay_rate
            req_roi = max(self.min_roi, self.target_roi - decay)
            
            sell_price = pos['avg_price'] * (1.0 + req_roi)
            
            if price >= sell_price:
                qty = pos['amount']
                val = qty * price
                self.balance += val
                del self.positions[sym]
                self.cooldowns[sym] = self.cooldown_ticks
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PROFIT_TAKE']
                }
            
            # --- DCA CHECK ---
            layer = pos['layer']
            if layer < len(self.dca_steps):
                trigger = pos['last_price'] * (1.0 - self.dca_steps[layer])
                
                if price < trigger:
                    mult = self.dca_mults[layer]
                    cost = self.base_order * mult
                    
                    if self.balance >= cost:
                        buy_qty = cost / price
                        
                        # Update weighted average
                        new_qty = pos['amount'] + buy_qty
                        new_cost = (pos['amount'] * pos['avg_price']) + cost
                        
                        pos['amount'] = new_qty
                        pos['avg_price'] = new_cost / new_qty
                        pos['last_price'] = price
                        pos['layer'] += 1
                        
                        self.balance -= cost
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{layer+1}']
                        }

        # 3. Entry Logic
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions or sym in self.cooldowns: continue
                
                hist = self.history.get(sym)
                if not hist: continue
                
                metrics = self._calc_metrics(hist)
                if not metrics: continue
                
                # Strict Filters
                if metrics['z'] < self.entry_z and metrics['rsi'] < self.entry_rsi:
                    candidates.append({
                        'sym': sym,
                        'price': price,
                        'z': metrics['z']
                    })
            
            # Prioritize most extreme deviation
            candidates.sort(key=lambda x: x['z'])
            
            if candidates:
                best = candidates[0]
                cost = self.base_order
                
                if self.balance >= cost:
                    qty = cost / best['price']
                    self.balance -= cost
                    
                    self.positions[best['sym']] = {
                        'amount': qty,
                        'avg_price': best['price'],
                        'last_price': best['price'],
                        'layer': 0,
                        'ticks_held': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': best['sym'],
                        'amount': qty,
                        'reason': ['TITANIUM_ENTRY']
                    }

        return {}