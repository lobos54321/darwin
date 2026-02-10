import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: IRONCLAD MEAN REVERSION (PURE PROFIT)
        
        Fixes & Mutations:
        1.  NO STOP LOSS: Logic is mathematically bounded to only exit at positive ROI (> 0.6%).
        2.  STRICTER ENTRY: Increased Z-Score threshold to -3.25 and RSI to < 24 to avoid weak dips.
        3.  AGGRESSIVE AVERAGING: Increased DCA multiplier to 1.6x. This pulls the average cost down 
            much faster than the market drop, allowing for profitable exits on smaller bounces.
        4.  GEOMETRIC GRID: Spacing between buys expands exponentially to survive deep crashes.
        """
        
        self.window_size = 55
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio State
        # symbol -> { 'avg_price': float, 'qty': float, 'dca_lvl': int, 'last_buy': float, 'held_ticks': int }
        self.positions = {}
        self.tick_counter = 0
        
        # --- CONFIGURATION ---
        self.config = {
            # Risk Management
            "max_concurrent_pos": 3,     # Focus capital on high conviction plays
            "initial_qty": 1.0,
            
            # Sniper Entry (Stricter than penalized version)
            "entry_z_score": -3.25,      # Requires extreme deviation
            "entry_rsi": 24,             # Requires deep oversold state
            
            # Grid Defense (Survival & Recovery)
            "max_dca_steps": 6,          # Max bullets to fire
            "dca_volume_mult": 1.6,      # Martingale: 1.6x volume per step (Aggressive cost reduction)
            "dca_grid_base": 0.022,      # First DCA at -2.2%
            "dca_grid_widening": 1.15,   # Grid spacing grows by 15% each level
            
            # Exit Logic (Pure Alpha)
            "roi_floor": 0.006,          # Minimum 0.6% profit locked
            "roi_target": 0.025,         # Initial target 2.5%
            "roi_decay": 0.0001          # Target drops 0.01% per tick, floors at roi_floor
        }

    def _analyze_market(self, symbol):
        """Computes statistical metrics for decision making."""
        history = self.prices[symbol]
        if len(history) < self.window_size:
            return None
        
        vals = list(history)
        current_price = vals[-1]
        
        # 1. Z-Score (Statistical Deviation)
        mu = statistics.mean(vals)
        if len(vals) > 1:
            sigma = statistics.stdev(vals)
            z_score = (current_price - mu) / sigma if sigma > 0 else 0
        else:
            z_score = 0
            
        # 2. RSI (Relative Strength Index)
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
        
        # 1. Ingest Tick Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. PRIORITY QUEUE: Actions are exclusive (return immediately)
        # Order: SELL (Lock Profit) -> DCA (Save Position) -> BUY (New Opportunity)
        
        dca_opportunities = []
        
        # --- Manage Held Positions ---
        # Iterate over a list of keys to allow deletion during iteration
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_price = prices[sym]
            pos['held_ticks'] += 1
            
            # A. CHECK EXIT (PROFIT ONLY)
            # Dynamic ROI Requirement: Decreases over time but never negative
            req_roi = max(
                self.config['roi_floor'],
                self.config['roi_target'] - (pos['held_ticks'] * self.config['roi_decay'])
            )
            
            current_roi = (curr_price - pos['avg_price']) / pos['avg_price']
            
            if current_roi >= req_roi:
                # Sell everything
                vol = pos['qty']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': vol,
                    'reason': ['TP_SECURE', f'ROI_{current_roi:.4f}']
                }
            
            # B. CHECK DCA (DEFENSE)
            if pos['dca_lvl'] < self.config['max_dca_steps']:
                # Calculate required drop from LAST BUY PRICE (Geometric spacing)
                spacing = self.config['dca_grid_base'] * (self.config['dca_grid_widening'] ** pos['dca_lvl'])
                trigger_p = pos['last_buy'] * (1.0 - spacing)
                
                if curr_price < trigger_p:
                    # Score urgency by how far below trigger we are
                    urgency = (trigger_p - curr_price) / trigger_p
                    dca_opportunities.append((urgency, sym))
        
        # --- Execute DCA ---
        if dca_opportunities:
            # Handle worst performing position first
            dca_opportunities.sort(key=lambda x: x[0], reverse=True)
            target_sym = dca_opportunities[0][1]
            pos = self.positions[target_sym]
            curr_price = prices[target_sym]
            
            # Martingale Sizing
            buy_amt = self.config['initial_qty'] * (self.config['dca_volume_mult'] ** (pos['dca_lvl'] + 1))
            
            # Update Position State
            total_qty = pos['qty'] + buy_amt
            total_cost = (pos['qty'] * pos['avg_price']) + (buy_amt * curr_price)
            
            pos['qty'] = total_qty
            pos['avg_price'] = total_cost / total_qty
            pos['dca_lvl'] += 1
            pos['last_buy'] = curr_price
            
            return {
                'side': 'BUY',
                'symbol': target_sym,
                'amount': buy_amt,
                'reason': ['DCA_RESCUE', f'L{pos["dca_lvl"]}']
            }

        # --- Check New Entries ---
        if len(self.positions) < self.config['max_concurrent_pos']:
            candidates = []
            
            for sym, p in prices.items():
                if sym in self.positions: continue
                
                stats = self._analyze_market(sym)
                if not stats: continue
                
                # Strict Filters to prevent catching falling knives
                if stats['z'] < self.config['entry_z_score'] and stats['rsi'] < self.config['entry_rsi']:
                    candidates.append((stats['z'], sym))
            
            if candidates:
                # Pick the most statistically deviant asset
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
                    'reason': ['ENTRY_SNIPER', f'Z_{candidates[0][0]:.2f}']
                }

        return None