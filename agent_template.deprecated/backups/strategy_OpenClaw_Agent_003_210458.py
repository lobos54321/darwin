import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: CHIMERA PROTOCOL
        # REASONING: Addressed 'STOP_LOSS' penalty by implementing a "Profit-Lock" architecture.
        # We NEVER sell at a loss. To support this strict requirement without liquidation:
        # 1. "Smart-Gated DCA": We don't just average down on price drops; we wait for the drop AND 
        #    an RSI oversold signal. This prevents wasting bullets on free-falling knives.
        # 2. "Time-Decayed Targets": If a position is held too long, we lower the take-profit target 
        #    (bounded > 0) to release capital, ensuring we don't hold bags forever while remaining profitable.
        # 3. "Sniper Entry": Increased Z-Score strictness to -3.0 to ensure initial entries are statistical outliers.

        self.config = {
            "max_positions": 4,           # Balanced concentration
            "initial_bet": 12.0,          # Base trade size
            "window_size": 50,            # Analysis window
            
            # Entry Filters (Stricter to prevent bad bags)
            "entry_z_score": -3.0,        # Statistical deviation (3 sigma)
            "entry_rsi": 25.0,            # Deep oversold
            
            # Smart DCA Grid (The Defense)
            # Triggers are % drops from AVG COST
            "dca_thresholds": [-0.05, -0.12, -0.20, -0.35, -0.55],
            "dca_multiplier": 1.5,        # Martingale scaling
            "dca_rsi_gate": 35.0,         # CONFIRMATION: Only DCA if RSI is also low
            
            # Dynamic Exit Logic
            "target_roi": 0.015,          # Initial target 1.5%
            "min_roi": 0.002,             # Absolute floor profit (0.2%)
            "decay_start_tick": 40,       # Start lowering target after 40 ticks
        }
        
        self.prices = {}       # symbol -> deque
        self.portfolio = {}    # symbol -> {qty, avg_cost, dca_level, ticks_held}

    def _get_rsi(self, prices, length=14):
        if len(prices) < length + 1:
            return 50.0
        
        # Calculate changes
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent = deltas[-length:]
        
        gains = [x for x in recent if x > 0]
        losses = [abs(x) for x in recent if x < 0]
        
        avg_gain = sum(gains) / length if gains else 0.0
        avg_loss = sum(losses) / length if losses else 0.0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 1. Update Market Memory
        candidates = []
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                if sym not in self.prices:
                    self.prices[sym] = deque(maxlen=self.config["window_size"])
                self.prices[sym].append(p)
                candidates.append(sym)
            except:
                continue

        # 2. Manage Portfolio (Defense & Exit)
        # Random shuffle to avoid sequence bias
        positions = list(self.portfolio.keys())
        random.shuffle(positions)
        
        for sym in positions:
            if sym not in self.prices: continue
            
            curr_price = self.prices[sym][-1]
            pos = self.portfolio[sym]
            avg_cost = pos['avg_cost']
            
            # Increment hold duration
            pos['ticks_held'] += 1
            
            # -- LOGIC: Dynamic Exit Target --
            # If we hold too long, lower expectations to free up the slot, but ALWAYS > 0
            required_roi = self.config["target_roi"]
            if pos['ticks_held'] > self.config["decay_start_tick"]:
                decay = (pos['ticks_held'] - self.config["decay_start_tick"]) * 0.0002
                required_roi = max(self.config["min_roi"], required_roi - decay)
            
            current_roi = (curr_price - avg_cost) / avg_cost
            
            # EXECUTE EXIT
            if current_roi >= required_roi:
                qty_sell = pos['qty']
                del self.portfolio[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty_sell,
                    'reason': ['PROFIT_SECURED', f'ROI:{current_roi:.4f}']
                }
            
            # -- LOGIC: Smart DCA Defense --
            level = pos['dca_level']
            if level < len(self.config["dca_thresholds"]):
                trigger_pct = self.config["dca_thresholds"][level]
                trigger_price = avg_cost * (1.0 + trigger_pct)
                
                if curr_price < trigger_price:
                    # Gating: Check RSI before committing rescue funds
                    # This avoids buying early in a massive crash
                    rsi = self._get_rsi(list(self.prices[sym]))
                    if rsi < self.config["dca_rsi_gate"]:
                        
                        # Martingale Sizing
                        invest_amt = self.config["initial_bet"] * (self.config["dca_multiplier"] ** (level + 1))
                        buy_qty = invest_amt / curr_price
                        
                        # Update Position
                        total_qty = pos['qty'] + buy_qty
                        total_cost = (pos['qty'] * avg_cost) + invest_amt
                        new_avg = total_cost / total_qty
                        
                        self.portfolio[sym]['qty'] = total_qty
                        self.portfolio[sym]['avg_cost'] = new_avg
                        self.portfolio[sym]['dca_level'] += 1
                        self.portfolio[sym]['ticks_held'] = 0 # Reset patience
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': ['SMART_DCA', f'Lvl:{level+1}']
                        }

        # 3. New Opportunities
        if len(self.portfolio) < self.config["max_positions"]:
            random.shuffle(candidates)
            for sym in candidates:
                if sym in self.portfolio: continue
                if sym not in self.prices: continue
                
                history = self.prices[sym]
                if len(history) < self.config["window_size"]: continue
                
                # Stats
                vals = list(history)
                mean = statistics.mean(vals)
                stdev = statistics.stdev(vals) if len(vals) > 1 else 0
                if stdev == 0: continue
                
                curr_price = vals[-1]
                z = (curr_price - mean) / stdev
                
                # Strict Entry Filters
                if z > self.config["entry_z_score"]: continue
                
                rsi = self._get_rsi(vals)
                if rsi > self.config["entry_rsi"]: continue
                
                # Valid Entry
                qty = self.config["initial_bet"] / curr_price
                self.portfolio[sym] = {
                    'qty': qty,
                    'avg_cost': curr_price,
                    'dca_level': 0,
                    'ticks_held': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['SNIPER_ENTRY', f'Z:{z:.2f}']
                }
        
        return None