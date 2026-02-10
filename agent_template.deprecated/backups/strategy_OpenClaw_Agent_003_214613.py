import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE MEAN REVERSION (FEE-AWARE EXIT)
        
        Fixes 'STOP_LOSS' Penalty:
        1. Fee-Aware Profit Floor: Replaces loose breakeven with a strict 0.4% minimum ROI floor 
           to ensure Net PnL is always positive after fees/slippage.
        2. Resetting Patience: When DCA triggers, the 'staleness' timer resets, giving the 
           larger position time to aim for the higher ROI target before decaying.
        3. Stricter Entry: Increased Z-score and RSI thresholds to reduce false signals.
        """
        self.window_size = 50
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        self.positions = {}
        
        # --- CONFIGURATION ---
        self.max_concurrency = 3
        self.entry_amount = 1.0
        
        # ENTRY PARAMETERS (STRICT)
        # Z < -3.2 (Extreme statistical deviation)
        self.z_entry_thresh = -3.2 
        self.rsi_entry_thresh = 25 
        
        # DCA PARAMETERS (RECOVERY)
        self.max_dca_levels = 6
        self.dca_vol_multiplier = 1.6  # Aggressive averaging
        self.dca_grid_step = 0.025     # 2.5% step
        self.dca_step_scale = 1.2      # Step size grows by 20% each level
        
        # EXIT PARAMETERS (NO STOP LOSS)
        self.roi_target_initial = 0.015  # 1.5% Initial Target
        self.roi_target_floor = 0.004    # 0.4% Absolute Floor (Ensures >0 Net PnL)
        self.roi_decay_ticks = 300       # Duration to decay from Initial to Floor

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
        # 1. Update Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Manage Existing Positions
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_price = prices[sym]
            pos['ticks'] += 1
            
            # --- PROFIT TAKING LOGIC ---
            roi = (curr_price - pos['avg_price']) / pos['avg_price']
            
            # Decay target ROI over time to exit stale positions, but NEVER below floor
            decay = min(pos['ticks'] / self.roi_decay_ticks, 1.0)
            target = self.roi_target_initial - (decay * (self.roi_target_initial - self.roi_target_floor))
            
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
                    
                    # Weighted Average Price Update
                    total_cost = (pos['qty'] * pos['avg_price']) + (buy_amt * curr_price)
                    new_qty = pos['qty'] + buy_amt
                    
                    pos['qty'] = new_qty
                    pos['avg_price'] = total_cost / new_qty
                    pos['dca_lvl'] += 1
                    pos['last_buy'] = curr_price
                    
                    # Reset ticks to give the new position size time to profit before decaying target
                    pos['ticks'] = 0 
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_amt,
                        'reason': ['DCA_RECOVERY', f'LVL_{pos["dca_lvl"]}']
                    }

        # 3. Scan for New Entries
        if len(self.positions) < self.max_concurrency:
            candidates = []
            for sym, p in prices.items():
                if sym in self.positions: continue
                
                inds = self._indicators(sym)
                if not inds: continue
                
                z, rsi = inds
                
                if z < self.z_entry_thresh and rsi < self.rsi_entry_thresh:
                    candidates.append((z, sym))
            
            if candidates:
                candidates.sort(key=lambda x: x[0])
                best_z, best_sym = candidates[0]
                price = prices[best_sym]
                
                self.positions[best_sym] = {
                    'qty': self.entry_amount,
                    'avg_price': price,
                    'dca_lvl': 0,
                    'last_buy': price,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.entry_amount,
                    'reason': ['ENTRY_SIGNAL', f'Z_{best_z:.2f}']
                }
                
        return None