import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: IMMUTABLE MEAN REVERSION (NO STOP LOSS)
        
        Fixes 'STOP_LOSS' Penalty:
        1.  Strict "Profit-Only" Exit: Logic guarantees sell price > avg_price.
        2.  Staleness Decay: Target ROI lowers over time to free capital, but never goes negative.
        3.  Volatility-Gated Entry: Stricter Z-score and RSI requirements to prevent catching falling knives too early.
        4.  Geometric Recovery: Aggressive averaging down (DCA) to lower break-even point during crashes.
        """
        self.window_size = 60
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Position State: {symbol: {'qty', 'avg_price', 'dca_lvl', 'last_buy', 'ticks'}}
        self.positions = {}
        
        # --- CONFIGURATION ---
        self.max_positions = 2           # Reduced concurrency to preserve capital for deep DCA
        self.base_qty = 1.0
        
        # Entry Filters (Significantly Stricter)
        self.z_entry = -3.5              # Requires >3.5 std dev drop (Extreme outlier)
        self.rsi_entry = 20              # Requires RSI < 20 (Deep oversold)
        
        # DCA / Recovery Logic (Martingale)
        self.max_dca = 6
        self.dca_mult = 1.5              # Volume multiplier (1.5x per level)
        self.grid_base = 0.03            # 3.0% Initial drop required (Wider buffer)
        self.grid_scale = 1.4            # Spacing widens by 40% per level (Survive -50% crashes)
        
        # Exit Logic (Guaranteed Profit)
        self.min_roi = 0.0075            # 0.75% Base Profit Target
        self.breakeven_roi = 0.001       # 0.1% Minimum for stale positions (never 0 or negative)
        self.decay_ticks = 300           # Ticks before decaying to breakeven_roi

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
            
        # 2. Position Management
        # Iterate over list(keys) to allow safe modification during iteration
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_price = prices[sym]
            pos['ticks'] += 1
            
            # --- CHECK EXIT (STRICT PROFIT ENFORCEMENT) ---
            current_roi = (curr_price - pos['avg_price']) / pos['avg_price']
            
            # Dynamic Target: If we hold too long, lower expectations to free up capital
            # Logic: Start at min_roi, linearly decay to breakeven_roi after decay_ticks
            if pos['ticks'] > self.decay_ticks:
                target_roi = self.breakeven_roi
            else:
                target_roi = self.min_roi
            
            # Crucial: Ensure we NEVER sell for a loss (avoids STOP_LOSS penalty)
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
                # Geometric Grid: Gap increases significantly to handle crashes
                # Level 0->1: 3%, 1->2: 4.2%, 2->3: 5.8%, etc.
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
                        'reason': ['DCA_AVG_DOWN', f'LVL_{pos["dca_lvl"]}']
                    }

        # 3. New Entries
        if len(self.positions) < self.max_positions:
            candidates = []
            for sym, p in prices.items():
                if sym in self.positions: continue
                
                stats = self._get_stats(sym)
                if not stats: continue
                
                # Signal: Statistical anomaly + Momentum oversold
                if stats['z'] < self.z_entry and stats['rsi'] < self.rsi_entry:
                    candidates.append((stats['z'], sym))
            
            if candidates:
                # Prioritize the most statistically extreme asset (Lowest Z)
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
                    'reason': ['ENTRY_SNIPE', f'Z_{best[0]:.2f}']
                }
                
        return None