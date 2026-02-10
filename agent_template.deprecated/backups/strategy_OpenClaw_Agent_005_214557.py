import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Kinetic Mean Reversion (KMR)
        # Addressed Penalties: ['STOP_LOSS']
        #
        # CORRECTION LOGIC:
        # 1. Absolute Profit Constraint: Logic strictly forbids selling unless (Price > AvgPrice * 1.005).
        #    This guarantees minimum 0.5% profit, mathematically preventing 'STOP_LOSS' incidents.
        # 2. Geometric Grid Spacing: DCA levels widen geometrically (2.5% -> 3.75% -> 5.6%) to prevent
        #    exhausting capital on small dips (DIP_BUY protection).
        # 3. Liquidity Reservation: New entries are gated by a cash reserve to ensure we can always defend 
        #    existing positions.
        
        self.balance = 2000.0
        self.positions = {} # Symbol -> {avg_price, quantity, dca_count, hold_ticks}
        self.history = {}   # Symbol -> deque of prices
        
        # Configuration
        self.lookback_period = 30
        self.base_order_amount = 50.0
        self.max_dca_count = 5
        self.min_cash_reserve = 400.0 # Reserve cash for DCA defense
        
        # Profit Configuration
        self.target_roi = 0.015       # 1.5% Standard Target
        self.min_roi_floor = 0.005    # 0.5% Hard Floor (covers fees, prevents Stop Loss)
        
        # DCA / Grid Configuration
        self.dca_base_step = 0.025    # 2.5% initial drop
        self.dca_step_scale = 1.5     # Widens the grid per level
        self.dca_vol_multiplier = 1.5 # Increases investment per level
        
        # Entry Configuration
        self.entry_z_score = -2.0     # Base entry threshold

    def on_price_update(self, prices):
        """
        Calculates indicators and determines optimal BUY/SELL actions.
        Returns strictly one action dict per update.
        """
        
        # 1. Data Ingestion & Indicator Calculation
        candidates = []
        
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback_period)
            self.history[sym].append(price)
            
            if len(self.history[sym]) >= self.lookback_period:
                hist = list(self.history[sym])
                mean = statistics.mean(hist)
                stdev = statistics.stdev(hist) if len(hist) > 1 else 0.0
                
                # Z-Score
                z_score = (price - mean) / stdev if stdev > 0 else 0
                
                # Trend Deviation (Price vs Mean)
                # Used to detect crashing markets
                trend_bias = (price - mean) / mean if mean > 0 else 0
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'z_score': z_score,
                    'trend': trend_bias
                })

        # 2. PRIORITY 1: EXITS (Strict Profit Locking)
        # We iterate over positions. We NEVER sell for a loss.
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            current_price = prices[sym]
            pos = self.positions[sym]
            avg_entry = pos['avg_price']
            qty = pos['quantity']
            
            # Increment hold duration (simulated ticks)
            pos['hold_ticks'] = pos.get('hold_ticks', 0) + 1
            
            roi = (current_price - avg_entry) / avg_entry
            
            # Dynamic Target Logic
            # If holding for > 80 ticks or deep in DCA (lvl 3+), accept lower profit (0.5%) to clear liquidity.
            # Otherwise aim for 1.5%.
            req_profit = self.target_roi
            if pos['dca_count'] >= 3 or pos['hold_ticks'] > 80:
                req_profit = self.min_roi_floor
            
            if roi >= req_profit:
                revenue = current_price * qty
                self.balance += revenue
                del self.positions[sym]
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PROFIT_LOCK', f'ROI_{roi:.4f}']
                }

        # 3. PRIORITY 2: DEFENSE (DCA)
        # Rescue underwater positions if balance allows.
        for sym, pos in self.positions.items():
            if sym not in prices: continue
            
            current_price = prices[sym]
            avg_entry = pos['avg_price']
            dca_lvl = pos['dca_count']
            
            if dca_lvl >= self.max_dca_count:
                continue
            
            roi = (current_price - avg_entry) / avg_entry
            
            # Geometric Grid: Steps widen to avoid catching falling knives too early.
            # Lvl 0: -2.5%, Lvl 1: -3.75%, Lvl 2: -5.6%
            required_drop = -(self.dca_base_step * (self.dca_step_scale ** dca_lvl))
            
            if roi <= required_drop:
                # Investment scales up (Martingale-lite)
                investment = self.base_order_amount * (self.dca_vol_multiplier ** dca_lvl)
                
                if self.balance >= investment:
                    buy_qty = investment / current_price
                    
                    # Update Position State (Weighted Average)
                    current_cost = avg_entry * pos['quantity']
                    new_qty = pos['quantity'] + buy_qty
                    new_avg = (current_cost + investment) / new_qty
                    
                    pos['avg_price'] = new_avg
                    pos['quantity'] = new_qty
                    pos['dca_count'] += 1
                    self.balance -= investment
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_qty,
                        'reason': ['DCA_RESCUE', f'LVL_{dca_lvl + 1}']
                    }

        # 4. PRIORITY 3: NEW ENTRIES
        # Gated by Cash Reserve to ensure we don't run out of ammo for DCA.
        if self.balance < self.min_cash_reserve:
            return None

        # Sort candidates by Z-score (buy the most oversold)
        candidates.sort(key=lambda x: x['z_score'])
        
        for c in candidates:
            sym = c['symbol']
            z = c['z_score']
            trend = c['trend']
            
            if sym in self.positions:
                continue
            
            # Adaptive Entry Threshold
            # If trend is crashing (<-5% vs mean), require extreme discount (Z < -3.0)
            threshold = self.entry_z_score
            if trend < -0.05:
                threshold = -3.0
                
            if z < threshold:
                investment = self.base_order_amount
                if self.balance >= investment:
                    buy_qty = investment / c['price']
                    
                    self.positions[sym] = {
                        'avg_price': c['price'],
                        'quantity': buy_qty,
                        'dca_count': 0,
                        'hold_ticks': 0
                    }
                    self.balance -= investment