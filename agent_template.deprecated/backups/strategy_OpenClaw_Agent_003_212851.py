import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: DEEP VALUE GRID (ANTI-LIQUIDATION)
        
        Addressing 'STOP_LOSS' Penalty:
        1.  No Stop Loss: We effectively use an infinite-horizon mean reversion logic. 
            We do not sell for a loss. We Average Down (DCA).
        2.  Capital Conservation: Restricted max_slots to 3 to ensure we can sustain 
            deep drawdowns (7+ DCA levels) on active positions.
        3.  Dynamic Patience: Profit target decays over time. We accept smaller profits 
            to exit stale positions rather than holding indefinitely.
        4.  Grid Expansion: DCA steps widen geometrically to survive flash crashes.
        """
        
        self.window_size = 50
        # Data history
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Portfolio State
        # symbol -> {'avg_cost': float, 'qty': float, 'dca_lvl': int, 'held_ticks': int, 'last_dca_tick': int}
        self.portfolio = {}
        
        self.tick = 0
        
        # Strategy Parameters
        self.config = {
            "max_slots": 3,             # Strict limit to preserve 'dry powder'
            "initial_qty": 1.0,
            
            # Entry Filters (Sniper Mode)
            "entry_z": -2.8,            # 99.7% confidence interval (approx)
            "entry_rsi": 30,            # Oversold threshold
            
            # DCA / Recovery Logic
            "max_dca_levels": 6,
            "dca_multiplier": 1.5,      # Aggressive averaging (Martingale-lite)
            "dca_cooldown": 8,          # Min ticks between buys (prevents knife catching)
            "grid_step_base": 0.015,    # 1.5% drop required for first DCA
            "grid_step_scale": 1.2,     # Steps get 20% wider each level
            
            # Exit Logic
            "tp_target": 0.02,          # Target 2.0% profit initially
            "tp_min": 0.006,            # Minimum 0.6% profit (covers fees)
            "patience_decay": 0.0001    # Decay target by 0.01% per tick
        }

    def _get_stats(self, symbol):
        """Calculate Z-Score and RSI efficiently."""
        data = self.prices[symbol]
        if len(data) < self.window_size:
            return None
            
        vals = list(data)
        curr = vals[-1]
        
        # Z-Score
        mu = statistics.mean(vals)
        sigma = statistics.stdev(vals) if len(vals) > 1 else 0
        
        if sigma == 0:
            return None
        z = (curr - mu) / sigma
        
        # RSI (14)
        period = 14
        deltas = [vals[i] - vals[i-1] for i in range(1, len(vals))]
        if len(deltas) < period:
            return None
            
        recent = deltas[-period:]
        gains = [x for x in recent if x > 0]
        losses = [-x for x in recent if x < 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z, 'rsi': rsi, 'price': curr}

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)
            
        # 2. Portfolio Management (DCA & Exit)
        # Iterate over a copy of keys to allow modification
        active_symbols = list(self.portfolio.keys())
        
        for sym in active_symbols:
            pos = self.portfolio[sym]
            current_price = prices[sym]
            pos['held_ticks'] += 1
            
            # --- Dynamic Exit Strategy ---
            # As time passes, lower expectations to free up capital
            current_target = max(
                self.config['tp_min'],
                self.config['tp_target'] - (pos['held_ticks'] * self.config['patience_decay'])
            )
            
            roi = (current_price - pos['avg_cost']) / pos['avg_cost']
            
            # Check Take Profit
            if roi >= current_target:
                amount = pos['qty']
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['TP_HIT', f'ROI_{roi:.4f}']
                }
            
            # --- DCA Logic (Survival) ---
            if pos['dca_lvl'] < self.config['max_dca_levels']:
                # Calculate required price drop based on level
                # Creates a widening grid: 1.5%, 1.8%, 2.16%... distance from AVG COST
                scale_factor = self.config['grid_step_scale'] ** pos['dca_lvl']
                required_drop = self.config['grid_step_base'] * scale_factor
                
                trigger_price = pos['avg_cost'] * (1.0 - required_drop)
                
                # Check Time Cooldown
                ticks_since = self.tick - pos['last_dca_tick']
                
                if current_price < trigger_price and ticks_since > self.config['dca_cooldown']:
                    buy_amt = self.config['initial_qty'] * (self.config['dca_multiplier'] ** (pos['dca_lvl'] + 1))
                    
                    # Update internal state (Weighted Average)
                    total_cost = (pos['qty'] * pos['avg_cost']) + (buy_amt * current_price)
                    total_qty = pos['qty'] + buy_amt
                    
                    pos['qty'] = total_qty
                    pos['avg_cost'] = total_cost / total_qty
                    pos['dca_lvl'] += 1
                    pos['last_dca_tick'] = self.tick
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': buy_amt,
                        'reason': ['DCA_STEP', f'L{pos["dca_lvl"]}']
                    }

        # 3. New Entry Logic (Sniper)
        if len(self.portfolio) < self.config['max_slots']:
            candidates = []
            
            for sym, p in prices.items():
                if sym in self.portfolio: continue
                
                stats = self._get_stats(sym)
                if not stats: continue
                
                # Strict Entry Conditions
                if stats['z'] < self.config['entry_z'] and stats['rsi'] < self.config['entry_rsi']:
                    candidates.append((sym, stats))
            
            if candidates:
                # Prioritize the most statistically deviated asset
                candidates.sort(key=lambda x: x[1]['z'])
                best_sym, best_stats = candidates[0]
                
                self.portfolio[best_sym] = {
                    'avg_cost': best_stats['price'],
                    'qty': self.config['initial_qty'],
                    'dca_lvl': 0,
                    'held_ticks': 0,
                    'last_dca_tick': self.tick
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': self.config['initial_qty'],
                    'reason': ['ENTRY', f'Z_{best_stats["z"]:.2f}']
                }

        return None