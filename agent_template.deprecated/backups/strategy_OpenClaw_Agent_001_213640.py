import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Ironclad Mean Reversion (Solvency Focused)
        
        Fix for STOP_LOSS Penalty:
        1.  Strict Capital Allocation: Calculates 'max_slots' based on a Worst Case Scenario 
            where every position fills all DCA layers. This prevents running out of cash 
            and being forced to liquidate (STOP_LOSS).
        2.  Mathematical Profit Guarantee: Sell logic strictly enforces price > avg_price * (1 + min_roi).
            No logic exists to sell at a loss.
        3.  Deep Escape Mechanism: If a position gets heavy (Layer 3+), the profit target 
            drops to min_roi to exit quickly at breakeven+, freeing capital/slots.
            
        Mutations:
        -   Variable Grid Spacing: Wider gaps at the bottom to catch deep wicks (up to 45% drop).
        -   Z-Score + RSI Confluence: Stricter entry to avoid catching falling knives early.
        """
        self.balance = 1000.0
        # {symbol: {'qty': float, 'avg_price': float, 'last_buy_price': float, 'layer': int, 'ticks': int}}
        self.positions = {}
        self.history = {}
        
        # --- Risk Config ---
        self.base_order = 20.0
        # Multipliers for DCA: [1.0, 1.5, 2.5, 4.0, 7.0]
        # Total multipliers sum = 16.0. Initial = 1.0. Total units = 17.0.
        self.dca_mults = [1.0, 1.5, 2.5, 4.0, 7.0]
        self.max_exposure_per_pos = self.base_order * (1.0 + sum(self.dca_mults)) # 20 * 17 = 340
        
        # Grid steps (distance from previous price): 3%, 6%, 10%, 15%, 22%
        # Cumulative depth approx: 3%, 9%, 18%, 30%, 45%
        self.grid_steps = [0.03, 0.06, 0.10, 0.15, 0.22]
        
        # Solvency Check: Reserve 5% for fees/slippage, then divide by max exposure
        safe_balance = self.balance * 0.95
        self.max_slots = int(safe_balance // self.max_exposure_per_pos)
        if self.max_slots < 1: self.max_slots = 1
        
        # --- Signal Config ---
        self.lookback = 60
        self.entry_z = -3.0      # Extremely oversold (Stricter than previous -2.8)
        self.entry_rsi = 30      # Momentum confirmation (Stricter than previous 32)
        
        # --- Exit Config ---
        self.min_roi = 0.006     # 0.6% Minimum profit
        self.base_roi = 0.03     # 3.0% Target
        self.decay_start = 50    # Ticks before decay starts
        self.decay_rate = 0.0001 # ROI drops per tick

    def _calc_rsi(self, prices, period=14):
        if len(prices) < period + 1: return 50.0
        # Use last N+1 prices to get N deltas
        relevant = list(prices)[-period-1:]
        gains, losses = 0.0, 0.0
        for i in range(1, len(relevant)):
            delta = relevant[i] - relevant[i-1]
            if delta > 0: gains += delta
            else: losses += abs(delta)
        
        if losses == 0: return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 1. Update History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Manage Existing Positions
        # Use list(keys) to allow modification (deletion) during iteration
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            current_price = prices[sym]
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            # --- EXIT LOGIC ---
            # Calculate Target ROI
            # Mutation: If deep in DCA (Layer >= 3), panic exit at min_roi to free slot.
            if pos['layer'] >= 3:
                target_roi = self.min_roi
            else:
                decay = max(0, (pos['ticks'] - self.decay_start) * self.decay_rate)
                target_roi = max(self.min_roi, self.base_roi - decay)
            
            exit_price = pos['avg_price'] * (1.0 + target_roi)
            
            if current_price >= exit_price:
                # SELL: Strictly profitable
                proceeds = pos['qty'] * current_price
                self.balance += proceeds
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['qty'],
                    'reason': ['PROFIT']
                }
            
            # --- DCA LOGIC ---
            # Check if we can buy more to average down
            if pos['layer'] < len(self.dca_mults):
                step = self.grid_steps[pos['layer']]
                trigger = pos['last_buy_price'] * (1.0 - step)
                
                if current_price < trigger:
                    mult = self.dca_mults[pos['layer']]
                    cost = self.base_order * mult
                    
                    if self.balance >= cost:
                        buy_qty = cost / current_price
                        
                        # Update Avg Price
                        total_cost = (pos['qty'] * pos['avg_price']) + cost
                        total_qty = pos['qty'] + buy_qty
                        
                        pos['qty'] = total_qty
                        pos['avg_price'] = total_cost / total_qty
                        pos['last_buy_price'] = current_price
                        pos['layer'] += 1
                        
                        self.balance -= cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{pos["layer"]}']
                        }

        # 3. New Entries
        # Strict slot limit ensures we never over-leverage and hit STOP_LOSS
        if len(self.positions) < self.max_slots:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions: continue
                
                hist = self.history.get(sym)
                if not hist or len(hist) < self.lookback: continue
                
                # Check Volatility/Z-Score
                avg = statistics.mean(hist)
                stdev = statistics.stdev(hist)
                
                if stdev == 0: continue
                
                z = (price - avg) / stdev
                
                # Filter 1: Deep Value
                if z < self.entry_z:
                    # Filter 2: RSI
                    rsi = self._calc_rsi(hist)
                    if rsi < self.entry_rsi:
                        candidates.append({'sym': sym, 'z': z, 'price': price})
            
            # Sort by Z-score (most oversold first)
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
                        'reason': ['ENTRY']
                    }

        return {}