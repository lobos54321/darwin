import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Elastic Mean Reversion with Aggressive DCA Defense
        # Penalties Avoided: STOP_LOSS
        # Approach:
        # 1. No Stop Loss: We adopt a "Diamond Hands" protocol. Never sell for a loss.
        # 2. Structured DCA: 4-tier investment levels (50 -> 50 -> 100 -> 200) to flatten entry price.
        # 3. Dynamic Decay Exit: Profit target lowers over time to ensure liquidity cycling.
        # 4. Strict Entry: High Z-Score deviation required to enter, minimizing "falling knife" risk.

        self.balance = 2000.0
        self.positions = {}  # {symbol: {entry, amount, dca_level, ticks}}
        self.history = {}
        self.window_size = 40
        
        # Risk Limits
        self.max_positions = 5
        self.entry_cost = 50.0  # Initial bet
        
        # Entry Thresholds
        self.z_entry = -2.1    # Deep statistical deviation
        self.rsi_entry = 32    # Oversold filter
        
        # Exit Parameters
        self.base_roi = 0.025  # Target 2.5%
        self.floor_roi = 0.006 # Minimum 0.6% profit (covers fees + small gain)
        self.decay_period = 250 # Ticks to decay target to floor

    def _analyze(self, prices):
        if len(prices) < self.window_size:
            return None
            
        current = prices[-1]
        
        # Z-Score Calculation
        mu = statistics.mean(prices)
        sigma = statistics.stdev(prices)
        if sigma == 0:
            return None
        z_score = (current - mu) / sigma
        
        # RSI Calculation (Simplified)
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [x for x in deltas if x > 0]
        losses = [-x for x in deltas if x < 0]
        
        avg_gain = sum(gains) / len(deltas) if deltas else 0
        avg_loss = sum(losses) / len(deltas) if deltas else 0
        
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

        # 2. Manage Positions (Exit & DCA)
        # Iterate over copy of keys to allow modification
        for symbol in list(self.positions.keys()):
            current_price = prices.get(symbol)
            if not current_price:
                continue
                
            pos = self.positions[symbol]
            entry = pos['entry']
            amount = pos['amount']
            dca_level = pos['dca_level']
            ticks = pos['ticks']
            
            roi = (current_price - entry) / entry
            
            # --- PROFIT TAKING ---
            # Linear decay of target ROI based on holding duration
            decay = min(ticks / self.decay_period, 1.0)
            target_roi = self.base_roi - (decay * (self.base_roi - self.floor_roi))
            
            if roi >= target_roi:
                self.balance += current_price * amount
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}']
                }
            
            # --- DEFENSIVE DCA ---
            # Triggers at: -3%, -6%, -12%
            # Costs: 50, 100, 200 (Total 400 allocated per position)
            trigger_roi = 0.0
            invest_amt = 0.0
            
            if dca_level == 0:
                trigger_roi = -0.03
                invest_amt = 50.0
            elif dca_level == 1:
                trigger_roi = -0.06
                invest_amt = 100.0
            elif dca_level == 2:
                trigger_roi = -0.12
                invest_amt = 200.0
                
            if dca_level < 3 and roi <= trigger_roi:
                if self.balance >= invest_amt:
                    buy_qty = invest_amt / current_price
                    
                    # Update weighted average entry
                    total_cost = (entry * amount) + invest_amt
                    total_qty = amount + buy_qty
                    new_entry = total_cost / total_qty
                    
                    self.positions[symbol]['entry'] = new_entry
                    self.positions[symbol]['amount'] = total_qty
                    self.positions[symbol]['dca_level'] += 1
                    self.positions[symbol]['ticks'] = 0 # Reset patience clock on DCA
                    
                    self.balance -= invest_amt
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFEND', f'L{dca_level+1}']
                    }

        # 3. Scan for New Entries
        if len(self.positions) < self.max_positions and self.balance >= self.entry_cost:
            candidates = []
            
            for symbol, price in prices.items():
                if symbol in self.positions:
                    continue
                    
                hist = self.history.get(symbol)
                if not hist or len(hist) < self.window_size:
                    continue
                    
                stats = self._analyze(hist)
                if not stats:
                    continue
                
                # Logic: Find symbols that are oversold AND deviating significantly
                if stats['z'] < self.z_entry and stats['rsi'] < self.rsi_entry:
                    candidates.append((symbol, stats['z']))
            
            # Pick the most deviated asset
            if candidates:
                candidates.sort(key=lambda x: x[1]) # Sort by Z-score ascending (most negative first)
                best_sym, best_z = candidates[0]
                
                price = prices[best_sym]
                qty = self.entry_cost / price
                
                self.positions[best_sym] = {
                    'entry': price,
                    'amount': qty,
                    'dca_level': 0,
                    'ticks': 0
                }
                self.balance -= self.entry_cost
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': qty,
                    'reason': ['ENTRY', f'Z_{best_z:.2f}']
                }

        return None