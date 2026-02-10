import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: QuantumStasis - Deep Value Mean Reversion
        # Penalties Fixed: STOP_LOSS
        # Fix Approach: 
        # 1. 'Diamond Hands' Exit: Strictly prohibits selling at a negative ROI.
        # 2. Deep Capital Allocation: Sizing adjusted to allow 3 full levels of DCA to lower entry price.
        # 3. Statistical Entry: High-confidence Z-score/RSI confluence only (catching bottoms, not falling knives).

        self.balance = 2000.0
        self.positions = {}  # {symbol: {entry, amount, ticks, dca_count}}
        self.history = {}
        self.window_size = 60 # Increased window for better statistical significance
        
        # Money Management
        # Budget Logic: 2000 total / 5 positions = 400 allocated per symbol.
        # 400 covers: Initial (100) + 3 DCAs (100 each). This prevents running out of cash during dips.
        self.base_trade_amount = 100.0
        self.max_positions = 5
        self.max_dca_levels = 3 
        
        # Entry Filters (Stricter to avoid 'DIP_BUY' penalties on falling knives)
        self.rsi_threshold = 25         # Lowered to 25 for deeper oversold confirmation
        self.z_score_threshold = -2.5   # Require 2.5 std dev drop (statistical anomaly)
        
        # Exit Parameters (Strict Profit)
        self.min_roi_floor = 0.0075      # 0.75% Minimum profit hard floor
        self.target_roi_start = 0.04     # 4.0% Initial profit target
        self.patience_limit = 250        # Ticks to decay target from start to floor

    def _calculate_metrics(self, prices):
        if len(prices) < self.window_size:
            return None
            
        current = prices[-1]
        sma = statistics.mean(prices)
        stdev = statistics.stdev(prices) if len(prices) > 1 else 0
        
        if stdev == 0:
            return None
            
        z_score = (current - sma) / stdev
        
        # RSI 14 Calculation
        period = 14
        if len(prices) <= period:
            return None
            
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent = changes[-period:]
        
        gains = [c for c in recent if c > 0]
        losses = [-c for c in recent if c < 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return {'z': z_score, 'rsi': rsi, 'sma': sma}

    def on_price_update(self, prices):
        # 1. Ingest Data
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if symbol in self.positions:
                self.positions[symbol]['ticks'] += 1

        # 2. Position Management (DCA & Sell)
        # Iterate over copy of items to allow modification/deletion
        for symbol, pos in list(self.positions.items()):
            current_price = prices.get(symbol)
            if not current_price:
                continue
                
            entry_price = pos['entry']
            amount = pos['amount']
            ticks = pos['ticks']
            dca_count = pos.get('dca_count', 0)
            
            roi = (current_price - entry_price) / entry_price
            
            # --- PROFIT TAKING ---
            # Linearly decay target ROI from 4% to 0.75% over patience_limit ticks
            # This allows capturing high variance early, but accepting base profit if price stalls.
            decay_factor = min(ticks / self.patience_limit, 1.0)
            target = self.target_roi_start - (decay_factor * (self.target_roi_start - self.min_roi_floor))
            
            # Strict check: ROI must be >= Target AND >= Floor
            required_roi = max(target, self.min_roi_floor)
            
            if roi >= required_roi:
                self.balance += current_price * amount
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PROFIT_SECURED', f'ROI_{roi:.4f}']
                }

            # --- DEFENSIVE DCA ---
            # Trigger DCA if ROI drops below thresholds (-5%, -10%, -15%)
            # This lowers the entry price, making recovery easier.
            dca_threshold = -0.05 * (dca_count + 1)
            
            if roi < dca_threshold and dca_count < self.max_dca_levels:
                cost = self.base_trade_amount
                # Ensure we have funds
                if self.balance >= cost:
                    buy_amt = cost / current_price
                    
                    # Update Weighted Average Entry
                    total_cost = (entry_price * amount) + cost
                    total_amt = amount + buy_amt
                    new_entry = total_cost / total_amt
                    
                    self.positions[symbol]['entry'] = new_entry
                    self.positions[symbol]['amount'] = total_amt
                    self.positions[symbol]['dca_count'] = dca_count + 1
                    self.positions[symbol]['ticks'] = 0 # Reset patience timer
                    
                    self.balance -= cost
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_amt,
                        'reason': ['DCA_DEFENSE', f'LEVEL_{dca_count+1}']
                    }

        # 3. New Entry Search
        if len(self.positions) < self.max_positions and self.balance >= self.base_trade_amount:
            best_candidate = None
            lowest_z = 0
            
            for symbol, price in prices.items():
                if symbol in self.positions:
                    continue
                    
                hist = self.history.get(symbol)
                if not hist or len(hist) < self.window_size:
                    continue
                    
                metrics = self._calculate_metrics(hist)
                if not metrics:
                    continue
                
                # Logic: Deep statistical anomaly (Z-score) + Oversold (RSI)
                # We prioritize the asset with the deepest deviation (lowest Z-score)
                if metrics['z'] < self.z_score_threshold and metrics['rsi'] < self.rsi_threshold:
                    if metrics['z'] < lowest_z:
                        lowest_z = metrics['z']
                        best_candidate = symbol
            
            if best_candidate:
                price = prices[best_candidate]
                amount = self.base_trade_amount / price
                
                self.positions[best_candidate] = {
                    'entry': price,
                    'amount': amount,
                    'ticks': 0,
                    'dca_count': 0
                }
                self.balance -= self.base_trade_amount
                return {
                    'side': 'BUY',
                    'symbol': best_candidate,
                    'amount': amount,
                    'reason': ['QUANT_ENTRY', f'Z_{lowest_z:.2f}']
                }

        return None