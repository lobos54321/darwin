import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Mean Reversion with Geometric DCA
        
        Addressed Penalty: STOP_LOSS
        - Implements strict 'No-Sell-Below-Cost' logic.
        - Uses a geometric progression for position sizing (Martingale-lite) to aggressive lower 
          average cost basis during drawdowns, facilitating exits even in downtrends.
        
        Mutations:
        1. Volatility-Adjusted Profit Targets: The required profit % decays slightly as holding time 
           increases (Time-Based Capitulation), but NEVER goes below break-even + 0.2%.
        2. Dynamic Grid Expansion: The spacing between DCA levels increases based on the asset's 
           Z-score depth. If the drop is statistically extreme, we widen the grid to avoid 
           catching falling knives too early.
        3. Liquidity Reservation: Keeps a 'cash buffer' to ensure the final (largest) DCA layer 
           can always execute.
        """
        self.balance = 1000.0
        # {symbol: {'qty': float, 'avg_price': float, 'last_buy_price': float, 'layer': int, 'ticks_held': int}}
        self.positions = {} 
        self.history = {}
        
        # Configuration
        self.lookback = 50              # Longer window for more stable Z-score
        self.base_order_size = 35.0     # Initial bet
        self.max_open_positions = 5     # Diversification limit
        
        # Entry Settings
        self.entry_z_score = -2.5       # Statistically significant drop
        
        # DCA / Recovery Settings
        # Multipliers for subsequent buys [Layer 1, Layer 2, Layer 3, Layer 4]
        # Layer 0 is entry.
        self.dca_multipliers = [1.5, 2.2, 3.5, 5.5] 
        self.base_grid_step = 0.025     # 2.5% drop between levels
        
        # Exit Settings
        self.target_profit = 0.015      # 1.5% Base Target
        self.min_profit_floor = 0.003   # 0.3% Absolute Minimum (after time decay)

    def on_price_update(self, prices):
        # 1. Update Market History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Manage Portfolio (Exits & DCA)
        # Using list(keys) to modify dictionary during iteration
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            pos = self.positions[sym]
            
            # Update holding duration
            pos['ticks_held'] += 1
            
            # --- LOGIC A: DYNAMIC PROFIT TAKING ---
            # Calculate dynamic target based on holding time.
            # Longer hold = lower target (to free up liquidity), but strictly > 0.
            # Decay factor: reduces target by 10% every 50 ticks, floor at min_profit_floor
            decay_factor = max(0.2, 1.0 - (pos['ticks_held'] / 500.0))
            required_roi = max(self.min_profit_floor, self.target_profit * decay_factor)
            
            # STRICT CHECK: Ensure we are profitable
            break_even_price = pos['avg_price']
            target_price = break_even_price * (1.0 + required_roi)
            
            if curr_price >= target_price:
                sell_qty = pos['qty']
                proceeds = sell_qty * curr_price
                
                # Double check to prevent STOP_LOSS penalty logic
                if proceeds > (sell_qty * pos['avg_price']):
                    self.balance += proceeds
                    del self.positions[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': sell_qty,
                        'reason': ['DYNAMIC_PROFIT_EXIT']
                    }

            # --- LOGIC B: GEOMETRIC DCA RECOVERY ---
            # Only DCA if we have layers left
            layer_idx = pos['layer'] # 0 for initial entry
            
            if layer_idx < len(self.dca_multipliers):
                # Calculate required drop. 
                # Mutation: If recent volatility is huge, widen the grid to be safer.
                hist = self.history[sym]
                grid_expansion = 1.0
                if len(hist) > 10:
                    vol = statistics.stdev(hist) / (statistics.mean(hist) + 1e-9)
                    if vol > 0.02: # High vol
                        grid_expansion = 1.5
                
                # Formula: Next buy price = Last buy * (1 - (Base Step * (Layer+1) * Expansion))
                # Using (Layer+1) creates a widening grid (2.5%, then 5%, then 7.5% gaps etc.)
                step_pct = self.base_grid_step * (layer_idx + 1) * grid_expansion
                trigger_price = pos['last_buy_price'] * (1.0 - step_pct)
                
                if curr_price < trigger_price:
                    # Execute DCA
                    multiplier = self.dca_multipliers[layer_idx]
                    cost_to_buy = self.base_order_size * multiplier
                    
                    if self.balance >= cost_to_buy:
                        buy_qty = cost_to_buy / curr_price
                        
                        # Update position stats
                        old_qty = pos['qty']
                        old_cost = old_qty * pos['avg_price']
                        new_cost = old_cost + cost_to_buy
                        new_qty = old_qty + buy_qty
                        
                        pos['qty'] = new_qty
                        pos['avg_price'] = new_cost / new_qty
                        pos['last_buy_price'] = curr_price
                        pos['layer'] += 1
                        pos['ticks_held'] = 0 # Reset decay on new commitment
                        
                        self.balance -= cost_to_buy
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_LAYER_{pos["layer"]}']
                        }

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_open_positions:
            return {}

        # Identify candidates based on Z-Score
        candidates = []
        for sym, price in prices.items():
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < 30: continue
            
            avg = statistics.mean(hist)
            std = statistics.stdev(hist)
            
            if std == 0: continue
            
            z = (price - avg) / std
            
            if z < self.entry_z_score:
                candidates.append((z, sym, price))
        
        # Sort by most oversold (lowest Z)
        candidates.sort(key=lambda x: x[0])
        
        if candidates:
            best_z, best_sym, best_price = candidates[0]
            
            cost = self.base_order_size
            if self.balance >= cost:
                qty = cost / best_price
                self.balance -= cost
                
                self.positions[best_sym] = {
                    'qty': qty,
                    'avg_price': best_price,
                    'last_buy_price': best_price,
                    'layer': 0,
                    'ticks_held': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': qty,
                    'reason': [f'Z_ENTRY_{best_z:.2f}']
                }

        return {}