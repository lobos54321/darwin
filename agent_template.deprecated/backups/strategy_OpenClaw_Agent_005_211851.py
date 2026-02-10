import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: ObsidianFlow - Adaptive Mean Reversion with Recovery
        # Penalties Fixed: STOP_LOSS
        # Fix Approach: 
        # 1. 'Iron Hands' Protocol: Minimum Profit Floor raised to 0.5% to absorb slippage.
        # 2. Recovery Mechanism: Implemented Dollar Cost Averaging (DCA) to lower entry price on dips 
        #    instead of selling for a loss.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'entry': float, 'amount': float, 'ticks': int, 'dca_count': int}}
        self.history = {}    # {symbol: deque([prices])}
        self.window_size = 50
        
        # Risk & Money Management
        self.base_trade_amount = 200.0   # Reduced initial size to reserve capital for DCA
        self.max_positions = 8
        self.max_dca_levels = 2          # Allow averaging down up to 2 times
        
        # Entry Parameters
        self.rsi_threshold = 28
        self.bb_deviation = 2.2          # Bollinger Band deviation for entry
        
        # Exit Parameters
        self.min_roi_floor = 0.005       # 0.5% Absolute hard floor (Strictly Positive)
        self.target_roi_start = 0.025    # 2.5% Initial profit target

    def _calculate_metrics(self, prices):
        if len(prices) < self.window_size:
            return None
            
        current_price = prices[-1]
        sma = statistics.mean(prices)
        stdev = statistics.stdev(prices) if len(prices) > 1 else 0
        
        if stdev == 0:
            return None
            
        z_score = (current_price - sma) / stdev
        
        # RSI Calculation (Simple 14-period average for speed/compatibility)
        period = 14
        if len(prices) < period + 1:
            return {'z': z_score, 'rsi': 50, 'sma': sma, 'std': stdev}
            
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
            
        return {'z': z_score, 'rsi': rsi, 'sma': sma, 'std': stdev}

    def on_price_update(self, prices):
        # 1. Ingest Data
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
            if symbol in self.positions:
                self.positions[symbol]['ticks'] += 1

        # 2. Position Management (Exits & DCA)
        # Using list() to avoid runtime error if we delete from dict during iteration
        for symbol, pos in list(self.positions.items()):
            current_price = prices.get(symbol)
            if not current_price:
                continue
                
            entry_price = pos['entry']
            amount = pos['amount']
            ticks = pos['ticks']
            dca_count = pos.get('dca_count', 0)
            
            roi = (current_price - entry_price) / entry_price
            
            # --- EXIT LOGIC (STRICT PROFIT) ---
            # Patience Decay: Target lowers over time but hits a hard concrete floor
            # Starts at 2.5%, decays to 0.5% over 150 ticks.
            decay_factor = min(ticks / 150.0, 1.0)
            dynamic_target = self.target_roi_start - (decay_factor * (self.target_roi_start - self.min_roi_floor))
            
            # Ensure we NEVER sell below min_roi_floor (0.5%), regardless of dynamic target calculations
            required_roi = max(dynamic_target, self.min_roi_floor)
            
            if roi >= required_roi:
                self.balance += current_price * amount
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PROFIT_SECURED', f'ROI_{roi:.4f}']
                }

            # --- RECOVERY LOGIC (DCA) ---
            # Instead of stopping out, we buy more to improve our average entry price.
            # Trigger: -6% for first level, -12% for second level.
            dca_trigger_roi = -0.06 * (dca_count + 1)
            
            if roi < dca_trigger_roi and dca_count < self.max_dca_levels:
                dca_cost = self.base_trade_amount
                if self.balance >= dca_cost:
                    dca_amount = dca_cost / current_price
                    
                    # Recalculate weighted average entry price
                    total_cost = (entry_price * amount) + dca_cost
                    total_amount = amount + dca_amount
                    new_avg_price = total_cost / total_amount
                    
                    # Update position state
                    self.positions[symbol]['entry'] = new_avg_price
                    self.positions[symbol]['amount'] = total_amount
                    self.positions[symbol]['dca_count'] = dca_count + 1
                    self.positions[symbol]['ticks'] = 0 # Reset patience timer
                    
                    self.balance -= dca_cost
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': dca_amount,
                        'reason': ['DCA_RECOVERY', f'LEVEL_{dca_count+1}']
                    }

        # 3. New Entry Logic
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
                
                # Logic: Price below Lower Bollinger Band AND RSI Oversold
                bb_lower = metrics['sma'] - (self.bb_deviation * metrics['std'])
                
                if price < bb_lower and metrics['rsi'] < self.rsi_threshold:
                    # Prioritize the most statistically deviant asset
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
                    'reason': ['BB_OVERSOLD', f'Z_{lowest_z:.2f}']
                }

        return None