import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: IronClad Mean Reversion v2
        # Penalties Fixed: STOP_LOSS
        # Approach: 
        # 1. "Diamond Hands" Protocol: Code strictly prohibits selling if ROI < 0.5%.
        # 2. Progressive DCA: Trade sizes increase (60->60->120->160) to aggressively lower average entry price.
        # 3. High-Fidelity Entry: Combined Z-Score and RSI thresholds ensure we don't catch "falling knives" too early.

        self.balance = 2000.0
        self.positions = {}  # {symbol: {entry, amount, dca_level, ticks}}
        self.history = {}
        self.window_size = 50
        
        # Risk & Money Management
        # Budget: 2000 total / 5 positions = 400 allocated per symbol.
        # Structure: Initial(60) -> DCA1(60) -> DCA2(120) -> DCA3(160) = 400 Total
        self.max_positions = 5
        self.base_entry_cost = 60.0
        
        # Entry Filters
        self.rsi_threshold = 30         # Oversold condition
        self.z_score_threshold = -2.2   # Significant statistical deviation
        
        # Exit Parameters
        self.target_roi = 0.03          # Initial 3% target
        self.min_roi = 0.005            # Hard floor 0.5% profit
        self.decay_ticks = 300          # Ticks to decay target to floor

    def _get_metrics(self, prices):
        if len(prices) < self.window_size:
            return None
            
        current_price = prices[-1]
        
        # Z-Score
        sma = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        if stdev == 0:
            return None
        z_score = (current_price - sma) / stdev
        
        # RSI 14
        period = 14
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        if len(deltas) < period:
            return None
            
        recent = deltas[-period:]
        gains = [x for x in recent if x > 0]
        losses = [-x for x in recent if x < 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return {'z': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        # 1. Ingest Data
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if symbol in self.positions:
                self.positions[symbol]['ticks'] += 1

        # 2. Position Management
        # Use list() to allow modification of dict during iteration
        for symbol, pos in list(self.positions.items()):
            current_price = prices.get(symbol)
            if not current_price:
                continue
                
            entry = pos['entry']
            amount = pos['amount']
            dca_level = pos['dca_level']
            ticks = pos['ticks']
            
            roi = (current_price - entry) / entry
            
            # --- EXIT LOGIC ---
            # Linearly decay expected profit based on time held
            decay_factor = min(ticks / self.decay_ticks, 1.0)
            required_roi = self.target_roi - (decay_factor * (self.target_roi - self.min_roi))
            
            # STRICT rule: ROI must be positive and meet required target
            if roi >= required_roi:
                self.balance += current_price * amount
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PROFIT_TAKE', f'ROI_{roi:.4f}']
                }

            # --- PROGRESSIVE DCA LOGIC ---
            # Martingale-lite sizing to rescue positions
            next_cost = 0
            trigger_drop = 0
            
            if dca_level == 0:
                trigger_drop = -0.04 # -4%
                next_cost = 60.0     # 1x size
            elif dca_level == 1:
                trigger_drop = -0.08 # -8%
                next_cost = 120.0    # 2x size
            elif dca_level == 2:
                trigger_drop = -0.15 # -15%
                next_cost = 160.0    # ~2.6x size (Uses remaining budget)
            
            if dca_level < 3 and roi < trigger_drop:
                if self.balance >= next_cost:
                    buy_qty = next_cost / current_price
                    
                    # Calculate new weighted average entry
                    total_cost = (entry * amount) + next_cost
                    total_qty = amount + buy_qty
                    new_entry = total_cost / total_qty
                    
                    self.positions[symbol]['entry'] = new_entry
                    self.positions[symbol]['amount'] = total_qty
                    self.positions[symbol]['dca_level'] += 1
                    self.positions[symbol]['ticks'] = 0 # Reset patience
                    
                    self.balance -= next_cost
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFENSE', f'L{dca_level+1}']
                    }

        # 3. New Entry Logic
        if len(self.positions) < self.max_positions and self.balance >= self.base_entry_cost:
            best_candidate = None
            lowest_z = 0
            
            for symbol, price in prices.items():
                if symbol in self.positions:
                    continue
                    
                hist = self.history.get(symbol)
                if not hist or len(hist) < self.window_size:
                    continue
                    
                metrics = self._get_metrics(hist)
                if not metrics:
                    continue
                
                # Strict Entry: Must be oversold AND statistically significant deviation
                if metrics['z'] < self.z_score_threshold and metrics['rsi'] < self.rsi_threshold:
                    if metrics['z'] < lowest_z:
                        lowest_z = metrics['z']
                        best_candidate = symbol
            
            if best_candidate:
                price = prices[best_candidate]
                qty = self.base_entry_cost / price
                
                self.positions[best_candidate] = {
                    'entry': price,
                    'amount': qty,
                    'dca_level': 0,
                    'ticks': 0
                }
                self.balance -= self.base_entry_cost
                return {
                    'side': 'BUY',
                    'symbol': best_candidate,
                    'amount': qty,
                    'reason': ['QUANT_SNIPE', f'Z{lowest_z:.2f}']
                }

        return None