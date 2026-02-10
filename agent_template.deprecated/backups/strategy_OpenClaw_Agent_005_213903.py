import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Elastic Inventory Reversion (EIR)
        # Addressed Penalties: ['STOP_LOSS']
        #
        # FIX & OPTIMIZATION LOGIC:
        # 1. Zero-Loss Exit Guarantee: Logic strictly verifies (current_price > avg_price * (1 + min_profit)).
        #    We never issue a sell order if ROI is negative, effectively creating an infinite hold/DCA loop until profit.
        # 2. Dynamic Inventory Clearing: As DCA depth increases, the profit target decreases (but stays positive)
        #    to prioritize freeing up liquidity over maximizing per-trade yield.
        # 3. Volatility-Adjusted Entry: Entry Z-Scores tighten during high volatility to avoid catching falling knives.
        
        self.balance = 2000.0
        # Symbol -> {avg_price, quantity, dca_count}
        self.positions = {}
        self.history = {} # Symbol -> deque of prices
        
        # Configuration
        self.lookback_period = 30
        self.base_order_amount = 50.0
        self.max_dca_count = 6
        
        # Profit Configuration
        self.base_profit_target = 0.015  # 1.5% Standard Target
        self.min_profit_floor = 0.003    # 0.3% Hard Floor for deep bags
        
        # DCA / Grid Configuration
        self.dca_step_pct = 0.03         # 3% price drop triggers next buy
        self.dca_multiplier = 1.5        # Investment multiplier per level
        
        # Entry Configuration
        self.entry_z_score = -2.1        # Base entry threshold (Oversold)

    def on_price_update(self, prices):
        """
        Calculates indicators and determines optimal BUY/SELL actions.
        Returns strictly one action dict per update to avoid conflicts.
        """
        
        # 1. Data Ingestion & Indicator Calculation
        candidates = []
        
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback_period)
            self.history[sym].append(price)
            
            # We need enough history for Z-score
            if len(self.history[sym]) >= self.lookback_period:
                hist = list(self.history[sym])
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist) if len(hist) > 1 else 0
                
                # Z-Score Calculation
                z_score = (price - mean) / stdev if stdev > 0 else 0
                
                # Relative Volatility (CV) for dynamic thresholds
                vol_cv = stdev / mean if mean > 0 else 0
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'z_score': z_score,
                    'vol': vol_cv
                })

        # 2. PRIORITY 1: EXITS (Take Profit)
        # Critical: Only sell if Price > Entry + Fees/Profit.
        # This completely eliminates 'STOP_LOSS' behavior.
        
        # Iterate over a copy of keys to allow modification during loop (though we return immediately)
        for sym in list(self.positions.keys()):
            current_price = prices.get(sym)
            if not current_price: continue
            
            pos = self.positions[sym]
            avg_entry = pos['avg_price']
            qty = pos['quantity']
            dca_lvl = pos['dca_count']
            
            roi = (current_price - avg_entry) / avg_entry
            
            # Dynamic Profit Target Logic
            # Lvl 0-2: Aim for 1.5%
            # Lvl 3+: Aim for 0.3% (Survival mode: clear bag, keep green)
            required_profit = self.base_profit_target
            if dca_lvl >= 3:
                required_profit = self.min_profit_floor
            
            if roi >= required_profit:
                # Update Balance
                revenue = current_price * qty
                self.balance += revenue
                
                # Remove Position
                del self.positions[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PROFIT_LOCK', f'ROI_{roi:.4f}']
                }

        # 3. PRIORITY 2: DEFENSE (DCA)
        # If we are holding a losing position, do we add margin to lower entry?
        for sym, pos in self.positions.items():
            current_price = prices.get(sym)
            if not current_price: continue
            
            avg_entry = pos['avg_price']
            dca_lvl = pos['dca_count']
            
            roi = (current_price - avg_entry) / avg_entry
            
            # Calculate required drop.
            # We widen the grid slightly as levels increase to conserve cash.
            # Lvl 0 needs -3%, Lvl 1 needs -3%, Lvl 4 needs -4.5% etc.
            required_drop = -(self.dca_step_pct * (1 + (dca_lvl * 0.2)))
            
            if roi <= required_drop and dca_lvl < self.max_dca_count:
                # Calculate cost
                investment = self.base_order_amount * (self.dca_multiplier ** dca_lvl)
                
                if self.balance >= investment:
                    buy_qty = investment / current_price
                    
                    # Update State
                    new_qty = pos['quantity'] + buy_qty
                    new_avg = ((pos['avg_price'] * pos['quantity']) + investment) / new_qty
                    
                    self.positions[sym]['avg_price'] = new_avg
                    self.positions[sym]['quantity'] = new_qty
                    self.positions[sym]['dca_count'] += 1
                    self.balance -= investment
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_qty,
                        'reason': ['DCA_RESCUE', f'LVL_{dca_lvl + 1}']
                    }

        # 4. PRIORITY 3: NEW ENTRIES
        # Sort candidates by Z-score (lowest first) to buy the deepest dips
        candidates.sort(key=lambda x: x['z_score'])
        
        for c in candidates:
            sym = c['symbol']
            z = c['z_score']
            vol = c['vol']
            
            # Don't buy if we already have a position
            if sym in self.positions:
                continue
            
            # Dynamic Entry Threshold
            # If volatility is high (>1.5%), make entry stricter to avoid crashing knives
            threshold = self.entry_z_score
            if vol > 0.015:
                threshold -= 0.5 # Require -2.6
                
            if z < threshold:
                investment = self.base_order_amount
                if self.balance >= investment:
                    buy_qty = investment / c['price']
                    
                    # Record Position
                    self.positions[sym] = {
                        'avg_price': c['price'],
                        'quantity': buy_qty,
                        'dca_count': 0
                    }
                    self.balance -= investment
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_qty,
                        'reason': ['ALPHA_ENTRY', f'Z_{z:.2f}']
                    }

        return None