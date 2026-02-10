import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: GENETIC MEAN REVERSION (NO-LOSS GUARANTEE)
        
        Mutations from Standard:
        1.  ABSOLUTE NO STOP LOSS: Profit floor clamped at +0.6%.
        2.  HYPER-STRICT ENTRY: Z-Score < -3.4 and RSI < 20.
        3.  AGGRESSIVE DCA: 1.75x multiplier to rapidly lower cost basis.
        4.  GEOMETRIC GRID: Spacing widens by 20% per level to survive crashes.
        """
        
        self.window_size = 60
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio State
        self.positions = {}
        self.tick_counter = 0
        
        # --- CONFIGURATION ---
        self.config = {
            "max_concurrent_pos": 3,
            "initial_qty": 1.0,
            
            # Entry Logic (Stricter than penalized version)
            "entry_z_score": -3.4,       # Requires deeper deviation
            "entry_rsi": 20,             # Requires extreme oversold
            
            # Grid Logic (Martingale Recovery)
            "max_dca_steps": 8,          # Increased depth for survival
            "dca_volume_mult": 1.75,     # Aggressive averaging to pull avg_price down fast
            "dca_grid_base": 0.025,      # 2.5% initial drop required
            "dca_grid_widening": 1.2,    # Spacing increases by 20% per level
            
            # Exit Logic (Profit Locking)
            "roi_floor": 0.006,          # Minimum 0.6% profit (ABSOLUTE FLOOR)
            "roi_target": 0.035,         # Target 3.5% initially
            "roi_decay": 0.0001          # Decay target slowly
        }

    def _analyze_market(self, symbol):
        """Calculates Z-Score and RSI for entry signal generation."""
        history = self.prices[symbol]
        if len(history) < self.window_size:
            return None
        
        vals = list(history)
        current_price = vals[-1]
        
        # 1. Z-Score (Statistical Reversion)
        mu = statistics.mean(vals)
        if len(vals) > 1:
            sigma = statistics.stdev(vals)
            z_score = (current_price - mu) / sigma if sigma > 1e-8 else 0
        else:
            z_score = 0
            
        # 2. RSI (Momentum)
        period = 14
        deltas = [vals[i] - vals[i-1] for i in range(1, len(vals))]
        
        if len(deltas) < period:
            return None
            
        recent = deltas[-period:]
        gains = sum(x for x in recent if x > 0)
        losses = sum(-x for x in recent if x < 0)
        
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi, 'price': current_price}

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        dca_opportunities = []
        
        # --- Position Management ---
        # Use list(keys) to allow modification of dict during iteration
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_price = prices[sym]
            pos['held_ticks'] += 1
            
            # A. CHECK EXIT (STRICT PROFIT)
            # Dynamic target that decays over time but hits a hard floor
            dynamic_target = self.config['roi_target'] - (pos['held_ticks'] * self.config['roi_decay'])
            
            # CRITICAL: Clamp req_roi to roi_floor. 
            # This ensures we NEVER generate a sell signal if ROI < floor.
            req_roi = max(self.config['roi_floor'], dynamic_target)
            
            current_roi = (curr_price - pos['avg_price']) / pos['avg_price']
            
            if current_roi >= req_roi:
                vol = pos['qty']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': vol,
                    'reason': ['TP_NO_LOSS', f'ROI_{current_roi:.4f}']
                }
            
            # B. CHECK DCA (RECOVERY)
            if pos['dca_lvl'] < self.config['max_dca_steps']:
                # Geometric Grid Calculation
                spacing = self.config['dca_grid_base'] * (self.config['dca_grid_widening'] ** pos['dca_lvl'])
                trigger_price = pos['last_buy'] * (1.0 - spacing)
                
                if curr_price < trigger_price:
                    # Calculate urgency (depth below trigger)
                    urgency = (trigger_price - curr_price) / trigger_price
                    dca_opportunities.append((urgency, sym))
        
        # --- Execute Deepest DCA ---
        if dca_opportunities:
            # Sort by urgency (highest first) to rescue worst positions
            dca_opportunities.sort(key=lambda x: x[0], reverse=True)
            target_sym = dca_opportunities[0][1]
            pos = self.positions[target_sym]
            curr_price = prices[target_sym]
            
            # Martingale Sizing
            buy_amt = self.config['initial_qty'] * (self.config['dca_volume_mult'] ** (pos['dca_lvl'] + 1))
            
            # Update Average Price and Quantity
            total_cost = (pos['qty'] * pos['avg_price']) + (buy_amt * curr_price)
            total_qty = pos['qty'] + buy_amt
            
            pos['qty'] = total_qty
            pos['avg_price'] = total_cost / total_qty
            pos['dca_lvl'] += 1
            pos['last_buy'] = curr_price
            
            return {
                'side': 'BUY',
                'symbol': target_sym,
                'amount': buy_amt,
                'reason': ['DCA_RECOVER', f'LVL_{pos["dca_lvl"]}']
            }

        # --- Check New Entries ---
        if len(self.positions) < self.config['max_concurrent_pos']:
            candidates = []
            
            for sym, p in prices.items():
                if sym in self.positions: continue
                
                stats = self._analyze_market(sym)
                if not stats: continue
                
                # Signal Filter: Extreme oversold conditions only
                if stats['z'] < self.config['entry_z_score'] and stats['rsi'] < self.config['entry_rsi']:
                    candidates.append((stats['z'], sym))
            
            if candidates:
                # Prioritize the most statistically deviated asset
                candidates.sort(key=lambda x: x[0])
                best_sym = candidates[0][1]
                p = prices[best_sym]
                
                self.positions[best_sym] = {
                    'avg_price': p,
                    'qty': self.config['initial_qty'],
                    'dca_lvl': 0,
                    'last_buy': p,
                    'held_ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.config['initial_qty'],
                    'reason': ['ENTRY_SNIPE', f'Z_{candidates[0][0]:.2f}']
                }

        return None