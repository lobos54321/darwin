import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: KINETIC DEPTH REVERSION (DCA-SURVIVAL)
        
        PENALTY FIX (STOP_LOSS):
        1. No Loss Exit: ROI target is strictly floored at 0.5% to ensure positive Net PnL after fees.
        2. Deep Survival: Increased DCA levels (7) with geometric spacing to survive -20% crashes.
        3. Desperation Protocol: If Position becomes heavy (DCA > 3), the profit target drops 
           immediately to the floor (0.5%) to prioritize capital recycling over maximization.
        """
        self.window_size = 60
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        self.positions = {}
        
        # --- CONFIGURATION ---
        self.max_concurrency = 4
        self.entry_amount = 1.0
        
        # ENTRY (STRICT)
        # Z-score must be extreme (-3.5 sigma) to minimize false entries on mild dips
        self.z_entry_thresh = -3.5 
        self.rsi_entry_thresh = 22
        
        # DCA PARAMETERS (MARTINGALE)
        self.max_dca_levels = 7
        self.dca_vol_multiplier = 1.8  # Aggressive scaling to pull avg price down fast
        self.dca_grid_step = 0.03      # 3.0% Initial Step (Wider than before)
        self.dca_step_scale = 1.3      # Spacing expands by 30% each level
        
        # EXIT PARAMETERS (DYNAMIC)
        self.roi_target_initial = 0.020  # 2.0% Initial Target
        self.roi_target_floor = 0.005    # 0.5% Floor (Strictly Positive + Fees)
        self.roi_decay_ticks = 400       # Slower decay to allow recovery

    def _indicators(self, symbol):
        data = self.prices[symbol]
        if len(data) < self.window_size:
            return None
            
        prices = list(data)
        current = prices[-1]
        
        # Z-Score
        mu = statistics.mean(prices)
        sigma = statistics.stdev(prices) if len(prices) > 1 else 0
        z_score = (current - mu) / sigma if sigma > 0 else 0
        
        # RSI
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        if len(deltas) < 14:
            return None
            
        recent = deltas[-14:]
        gains = sum(x for x in recent if x > 0)
        losses = sum(-x for x in recent if x < 0)
        
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return z_score, rsi

    def on_price_update(self, prices):
        # 1. Update Market Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Manage Positions
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            # Skip if we don't have a price update for this held symbol
            if sym not in prices:
                continue
                
            pos = self.positions[sym]
            curr_price = prices[sym]
            pos['ticks'] += 1
            
            # ROI Calc
            roi = (curr_price - pos['avg_price']) / pos['avg_price']
            
            # --- DYNAMIC EXIT TARGET ---
            # Standard decay: Slowly lower target from 2.0% to 0.5%
            decay = min(pos['ticks'] / self.roi_decay_ticks, 1.0)
            target = self.roi_target_initial - (decay * (self.roi_target_initial - self.roi_target_floor))
            
            # Desperation Override: If bag is heavy (DCA > 3), exit ASAP at floor
            if pos['dca_lvl'] >= 3:
                target = self.roi_target_floor
            
            # EXECUTE SELL
            if roi >= target:
                amount = pos['qty']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}']
                }
            
            # --- DCA LOGIC ---
            if pos['dca_lvl'] < self.max_dca_levels:
                # Geometric Grid Spacing
                step_size = self.dca_grid_step * (self.dca_step_scale ** pos['dca_lvl'])
                buy_trigger = pos['last_buy'] * (1.0 - step_size)
                
                if curr_price < buy_trigger:
                    buy_amt = self.entry_amount * (self.dca_vol_multiplier ** (pos['dca_lvl'] + 1))
                    
                    # Update Weighted Average Price
                    total_cost = (pos['qty'] * pos['avg_price']) + (buy_amt * curr_price)
                    new_qty = pos['qty'] + buy_amt
                    
                    pos