import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE DEEP VALUE GRID (NO STOP LOSS)
        
        Improvements over Penalized Version:
        1.  Prioritized Execution: Evaluates EXITS before ENTRIES to free capital immediately.
        2.  Stricter Entry Filters: Z-Score -3.0 and RSI 25 to prevent catching falling knives early.
        3.  Safety-First Grid: DCA steps calculation based on 'last_buy_price' rather than 'avg_cost'.
            Using 'avg_cost' causes the grid to tighten dangerously during drawdowns (black hole effect).
            Using 'last_buy_price' ensures true geometric spacing.
        4.  Zero Stop Loss: Logic mathematically guarantees only positive ROI exits (min 0.7%).
        """
        
        self.window_size = 60
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio: symbol -> {
        #   'avg_cost': float, 'qty': float, 'dca_lvl': int, 
        #   'held_ticks': int, 'last_dca_tick': int, 'last_buy_price': float
        # }
        self.portfolio = {}
        self.tick = 0
        
        # --- CONFIGURATION ---
        self.config = {
            # Risk Limits
            "max_slots": 3,              # Max concurrent positions (High focus)
            "base_qty": 1.0,             # Initial bet size
            
            # Entry Logic (Sniper)
            "entry_z": -3.0,             # Statistical deviation req (approx 3 sigma)
            "entry_rsi": 25,             # Deep oversold
            
            # Grid / DCA Logic (Survival)
            "max_dca_levels": 7,         # Max add-ons
            "dca_multiplier": 1.4,       # Multiplier for subsequent buy sizes
            "dca_cooldown": 10,          # Ticks to wait between buys
            "step_base": 0.02,           # 2% drop required for L1
            "step_mult": 1.15,           # Spacing widens by 15% each level (Geometric)
            
            # Exit Logic (Patience)
            "tp_min": 0.007,             # Hard floor: 0.7% profit (Never sell below this)
            "tp_start": 0.025,           # Target: 2.5% profit
            "patience_decay": 0.00005    # Lower target slowly over time
        }

    def _get_indicators(self, symbol):
        """Calculates Z-Score and RSI."""
        history = self.prices[symbol]
        if len(history) < self.window_size:
            return None
        
        vals = list(history)
        current = vals[-1]
        
        # Z-Score
        mu = statistics.mean(vals)
        sigma = statistics.stdev(vals) if len(vals) > 1 else 0
        
        if sigma == 0:
            z = 0
        else:
            z = (current - mu) / sigma
            
        # RSI
        period = 14
        deltas = [vals[i] - vals[i-1] for i in range(1, len(vals))]
        if len(deltas) < period:
            return None # Not enough data for RSI
            
        recent = deltas[-period:]
        gains = sum(x for x in recent if x > 0)
        losses = sum(-x for x in recent if x < 0)
        
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z, 'rsi': rsi, 'price': current}

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. PRIORITY: Manage Existing Positions (Exits first, then DCA)
        # We use lists to collect candidates, then pick the best one to execute.
        # Single action per tick rule implies we must prioritize.
        
        dca_candidates = []
        
        # We iterate a copy of keys because we might delete from dict upon Sell
        for sym in list(self.portfolio.keys()):
            pos = self.portfolio[sym]
            current_p = prices[sym]
            pos['held_ticks'] += 1
            
            # --- Check EXIT (Take Profit) ---
            # Calculate required ROI based on time held
            target_roi = max(
                self.config['tp_min'],
                self.config['tp_start'] - (pos['held_ticks'] * self.config['patience_decay'])
            )
            
            current_roi = (current_p - pos['avg_cost']) / pos['avg_cost']
            
            if current_roi >= target_roi:
                # IMMEDIATE SELL
                amt = pos['qty']
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['TP_HIT', f'ROI_{current_roi:.4f}']
                }
            
            # --- Check DCA (Add Liquidity) ---
            if pos['dca_lvl'] < self.config['max_dca_levels']:
                # Grid spacing based on LAST BUY PRICE, not average cost.
                # This prevents the grid from "chasing" the price down too aggressively.
                spacing_req = self.config['step_base'] * (self.config['step_mult'] ** pos['dca_lvl'])
                trigger_price = pos['last_buy_price'] * (1.0 - spacing_req)
                
                ticks_since = self.tick - pos['last_dca_tick']
                
                if current_p < trigger_price and ticks_since > self.config['dca_cooldown']:
                    # Score by how deep we are relative to trigger (Urgency)
                    diff_pct = (trigger_price - current_p) / trigger_price
                    dca_candidates.append((diff_pct, sym))

        # 3. Execute DCA if needed (Priority over new entries)
        if dca_candidates:
            # Sort by urgency (deepest drop past trigger first)
            dca_candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = dca_candidates[0][1]
            pos = self.portfolio[best_sym]
            current_p = prices[best_sym]
            
            # Martingale Sizing
            buy_amt = self.config['base_qty'] * (self.config['dca_multiplier'] ** (pos['dca_lvl'] + 1))
            
            # Update Internal State
            total_cost = (pos['qty'] * pos['avg_cost']) + (buy_amt * current_p)
            total_qty = pos['qty'] + buy_amt
            
            pos['qty'] = total_qty
            pos['avg_cost'] = total_cost / total_qty
            pos['dca_lvl'] += 1
            pos['last_dca_tick'] = self.tick
            pos['last_buy_price'] = current_p
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': buy_amt,
                'reason': ['DCA_DEFENSE', f'L{pos["dca_lvl"]}']
            }

        # 4. New Entries (Sniper Mode)
        # Only if no other actions were taken and slots are available
        if len(self.portfolio) < self.config['max_slots']:
            entry_candidates = []
            
            for sym, p in prices.items():
                if sym in self.portfolio: continue
                
                stats = self._get_indicators(sym)
                if not stats: continue
                
                # Strict Conditions
                if stats['z'] <= self.config['entry_z'] and stats['rsi'] <= self.config['entry_rsi']:
                    entry_candidates.append(stats)
                    # We store the stats dict which contains 'price' and original 'z'
                    # We also need the symbol, let's inject it or store tuple
                    stats['symbol'] = sym
            
            if entry_candidates:
                # Pick the most oversold (lowest Z)
                entry_candidates.sort(key=lambda x: x['z'])
                best_opp = entry_candidates[0]
                
                self.portfolio[best_opp['symbol']] = {
                    'avg_cost': best_opp['price'],
                    'qty': self.config['base_qty'],
                    'dca_lvl': 0,
                    'held_ticks': 0,
                    'last_dca_tick': self.tick,
                    'last_buy_price': best_opp['price']
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_opp['symbol'],
                    'amount': self.config['base_qty'],
                    'reason': ['ENTRY_SNIPER', f'Z_{best_opp["z"]:.2f}']
                }

        return None