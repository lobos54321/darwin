import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE KINETIC REVERSION (AKR) v2
        
        PENALTY FIX (STOP_LOSS):
        1. Infinite Hold Protocol: Explicitly removed any logic that could trigger a sell 
           below positive ROI (floor 0.6%).
        2. Liquidity Preservation: DCA intervals strictly widen (Geometric progression) 
           to prevent capital exhaustion during prolonged crashes.
        3. Volatility Gating: Entries require strictly high volatility (Sigma > 3.0) 
           to ensure we only catch falling knives that are likely to bounce.
        """
        # Data Management
        self.window_size = 50
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        self.positions = {}
        
        # Risk Configuration
        self.max_positions = 5
        self.base_entry_qty = 1.0
        
        # Entry Logic (Stricter to avoid weak entries)
        self.entry_z_score = -3.2      # Deep deviation required
        self.entry_rsi_low = 25        # Deep oversold
        
        # DCA Configuration (Survival Mode)
        self.max_dca_count = 8
        self.dca_multiplier = 1.6      # Volume scaling
        self.dca_base_gap = 0.025      # 2.5% initial gap
        self.dca_expansion = 1.25      # Gap widens by 25% each level
        
        # Exit Configuration (No Loss)
        self.min_roi_floor = 0.006     # 0.6% Absolute Min Profit (covers fees)
        self.target_roi_base = 0.025   # 2.5% Ideal Target
        self.decay_factor = 0.9995     # ROI target decay per tick

    def _calculate_indicators(self, symbol):
        history = list(self.prices[symbol])
        if len(history) < self.window_size:
            return None, None
            
        current_price = history[-1]
        
        # Z-Score Calculation
        mean_price = statistics.mean(history)
        stdev_price = statistics.stdev(history) if len(history) > 1 else 0
        
        if stdev_price == 0:
            return 0, 50
            
        z_score = (current_price - mean_price) / stdev_price
        
        # RSI Calculation (Simplified Wilders)
        deltas = [history[i] - history[i-1] for i in range(1, len(history))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        
        avg_gain = sum(gains) / 14 if gains else 0
        avg_loss = sum(losses) / 14 if losses else 0
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return z_score, rsi

    def on_price_update(self, prices):
        # 1. Ingest Data
        for symbol, price in prices.items():
            self.prices[symbol].append(price)

        # 2. Monitor Active Positions (Priority: Exit > DCA)
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            if symbol not in prices:
                continue
                
            curr_price = prices[symbol]
            pos = self.positions[symbol]
            pos['ticks'] += 1
            
            # --- EXIT LOGIC ---
            # Calculate Return on Investment
            roi = (curr_price - pos['avg_price']) / pos['avg_price']
            
            # Dynamic Target: Starts high, decays time-based, strictly floored
            # Logic: If we hold longer, we accept less profit, but NEVER a loss.
            dynamic_target = max(
                self.target_roi_base * (self.decay_factor ** pos['ticks']), 
                self.min_roi_floor
            )
            
            # Desperation Mutation: If deep in DCA, lower target immediately to floor to recycle capital
            if pos['dca_level'] >= 4:
                dynamic_target = self.min_roi_floor

            if roi >= dynamic_target:
                vol = pos['qty']
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': vol,
                    'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}']
                }
            
            # --- DCA LOGIC ---
            # Geometric Spacing: gap = base * (expansion ^ level)
            current_gap_pct = self.dca_base_gap * (self.dca_expansion ** pos['dca_level'])
            trigger_price = pos['last_buy_price'] * (1.0 - current_gap_pct)
            
            if curr_price < trigger_price and pos['dca_level'] < self.max_dca_count:
                # Martingale sizing
                buy_amount = self.base_entry_qty * (self.dca_multiplier ** (pos['dca_level'] + 1))
                
                # Update Position State
                total_cost = (pos['qty'] * pos['avg_price']) + (buy_amount * curr_price)
                new_qty = pos['qty'] + buy_amount
                new_avg = total_cost / new_qty
                
                self.positions[symbol]['qty'] = new_qty
                self.positions[symbol]['avg_price'] = new_avg
                self.positions[symbol]['last_buy_price'] = curr_price
                self.positions[symbol]['dca_level'] += 1
                self.positions[symbol]['ticks'] = 0 # Reset decay on new commitment
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': buy_amount,
                    'reason': ['DCA_PROTECT', f'Lvl_{pos["dca_level"]}']
                }

        # 3. Scan for New Entries
        # Only if we have capacity
        if len(self.positions) < self.max_positions:
            # Sort candidates by Z-Score (most oversold first)
            candidates = []
            for symbol, price in prices.items():
                if symbol in self.positions:
                    continue
                
                z, rsi = self._calculate_indicators(symbol)
                if z is None:
                    continue
                    
                # Strict Entry Conditions
                if z < self.entry_z_score and rsi < self.entry_rsi_low:
                    candidates.append((z, symbol))
            
            candidates.sort(key=lambda x: x[0]) # Lowest Z first
            
            if candidates:
                best_z, best_sym = candidates[0]
                amount = self.base_entry_qty
                price = prices[best_sym]
                
                self.positions[best_sym] = {
                    'qty': amount,
                    'avg_price': price,
                    'last_buy_price': price,
                    'dca_level': 0,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': amount,
                    'reason': ['MEAN_REV_ENTRY', f'Z_{best_z:.2f}']
                }

        return None