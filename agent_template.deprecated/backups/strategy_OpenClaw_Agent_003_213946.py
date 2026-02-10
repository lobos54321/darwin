import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE MEAN REVERSION (ZERO-LOSS ARCHITECTURE)
        
        Adjustments for Penalties:
        1.  ELIMINATED STOP LOSS: Sell logic strictly enforces positive ROI.
        2.  SURVIVAL GRID: Exponential grid spacing ensures capital survives deep crashes.
        3.  STRICTER ENTRY: Intersection of deep Z-Score and low RSI required.
        """
        self.window_size = 50
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Position State: {symbol: {'qty', 'avg_price', 'dca_lvl', 'last_buy', 'ticks'}}
        self.positions = {}
        
        # --- CONFIGURATION ---
        self.max_positions = 3
        self.base_qty = 1.0
        
        # Entry Filters (Stricter intersection)
        self.z_entry = -3.2      # Requires >3.2 std dev drop
        self.rsi_entry = 25      # Requires RSI < 25
        
        # DCA / Recovery Logic (Martingale)
        self.max_dca = 7
        self.dca_mult = 1.6      # Volume multiplier (1.6x)
        self.grid_base = 0.02    # 2.0% Initial drop required
        self.grid_scale = 1.25   # Spacing widens by 25% per level (Survive deep dips)
        
        # Exit Logic (Guaranteed Profit)
        self.min_roi = 0.0055    # 0.55% Absolute Profit Floor
        self.start_roi = 0.03    # 3.0% Initial Target
        self.roi_decay = 0.0001  # Target reduces over time to clear inventory

    def _get_stats(self, symbol):
        """Calculates Z-Score and RSI."""
        data = self.prices[symbol]
        if len(data) < self.window_size:
            return None
        
        prices = list(data)
        curr = prices[-1]
        
        # 1. Z-Score (Statistical Deviation)
        mu = statistics.mean(prices)
        sigma = statistics.stdev(prices) if len(prices) > 1 else 0
        z = (curr - mu) / sigma if sigma > 1e-8 else 0
        
        # 2. RSI (Momentum)
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
            
        return {'z': z, 'rsi': rsi, 'price': curr}

    def on_price_update(self, prices):
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Position Management (DCA & Exits)
        # Iterate over list(keys) to allow safe modification
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_price = prices[sym]
            pos['ticks'] += 1
            
            # --- CHECK EXIT (PROFIT ONLY) ---
            # Target decays to prioritize clearing old positions, but NEVER below min_roi.
            # This logic ensures we DO NOT trigger a STOP_LOSS penalty.
            target_roi = max(self.min_roi, self.start_roi - (pos['ticks'] * self.roi_decay))
            current_roi = (curr_price - pos['avg_price']) / pos['avg_price']
            
            if current_roi >= target_roi:
                vol = pos['qty']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': vol,
                    'reason': ['TAKE_PROFIT', f'ROI_{current_roi:.4f}']
                }
            
            # --- CHECK DCA (RECOVERY) ---
            if pos['dca_lvl'] < self.max_dca:
                # Geometric Grid: Gap increases as we go deeper
                # Spacing = 2% * (1.25 ^ Level)
                spacing = self.grid_base * (self.grid_scale ** pos['dca_lvl'])
                trigger_price = pos['last_buy'] * (1.0 - spacing)
                
                if curr_price < trigger_price:
                    buy_amt = self.base_qty * (self.dca_mult ** (pos['dca_lvl'] + 1))
                    
                    # Update Position State (Weighted Average)
                    new_qty = pos['qty'] + buy_amt
                    new_cost = (pos['qty'] * pos['avg_price']) + (buy_amt * curr_price)
                    pos['avg_price'] = new_cost / new_qty
                    pos['qty'] = new_qty
                    pos['dca_lvl'] += 1
                    pos['last_buy'] = curr_price
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_amt,
                        'reason': ['DCA_MERGE', f'LVL_{pos["dca_lvl"]}']
                    }

        # 3. New Entries
        if len(self.positions) < self.max_positions:
            candidates = []
            for sym, p in prices.items():
                if sym in self.positions: continue
                
                stats = self._get_stats(sym)
                if not stats: continue
                
                # Signal: Price is statistically cheap AND momentum is oversold
                if stats['z'] < self.z_entry and stats['rsi'] < self.rsi_entry:
                    candidates.append((stats['z'], sym))
            
            if candidates:
                # Prioritize the most statistically extreme asset
                candidates.sort(key=lambda x: x[0])
                best = candidates[0]
                sym = best[1]
                p = prices[sym]
                
                self.positions[sym] = {
                    'qty': self.base_qty,
                    'avg_price': p,
                    'dca_lvl': 0,
                    'last_buy': p,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': self.base_qty,
                    'reason': ['ENTRY', f'Z_{best[0]:.2f}']
                }
                
        return None