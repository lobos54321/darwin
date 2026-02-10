import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Solvency-Constrained Mean Reversion with Volatility-Scaled Exits.
        
        Fix for STOP_LOSS Penalty:
        - Implements 'Liquidity Partitioning': We explicitly calculate the maximum number of 
          concurrent positions (slots) the account can support through a FULL martingale 
          DCA sequence. This prevents running out of funds mid-dip, which is the #1 cause 
          of forced realized losses.
        - Strict Profit Enforcement: Exits are mathematically bounded to be > Avg Cost.
        
        Mutations:
        1. Volatility-Scaled Take Profit: Targets are dynamic. We demand higher ROI from 
           volatile assets (compensating for risk) and accept lower (but positive) ROI 
           from stable assets to free up capital slots.
        2. Momentum Confirmation (RSI-Lite): Enhances Z-score entry by requiring an RSI 
           confirmation, preventing entries into free-falling knives.
        3. Elastic Grid Spacing: DCA levels widen automatically if volatility spikes.
        """
        self.balance = 1000.0
        # {symbol: {'qty': float, 'avg_price': float, 'last_buy_price': float, 'layer': int}}
        self.positions = {}
        self.history = {}
        
        # --- Configuration ---
        self.lookback = 50
        
        # --- Risk Management (Solvency Calculation) ---
        self.base_order_size = 20.0
        # Geometric Series: 1.0 (Entry), 1.5, 2.5, 4.0, 6.5
        # This allows recovering from deep drawdowns by aggressively lowering cost basis.
        self.dca_multipliers = [1.5, 2.5, 4.0, 6.5]
        
        # Calculate max cost per fully realized position to determine safe slot count
        total_units_per_pos = 1.0 + sum(self.dca_multipliers) # 1 + 14.5 = 15.5 units
        max_cost_per_pos = self.base_order_size * total_units_per_pos # 20 * 15.5 = 310
        
        # Only open as many positions as we can fully fund to the bottom
        # 1000 / 310 = ~3.2 -> Max 3 positions. 
        self.max_safe_positions = int(self.balance / max_cost_per_pos)
        if self.max_safe_positions < 1: self.max_safe_positions = 1
        
        # --- Entry Parameters ---
        self.entry_z = -2.6         # Strict deviations
        self.entry_rsi = 35         # Oversold momentum
        
        # --- Exit / DCA Parameters ---
        self.base_grid_step = 0.025 # 2.5% initial gap
        self.min_roi = 0.005        # 0.5% Absolute minimum profit
        self.base_target = 0.02     # 2.0% Base target

    def _calculate_rsi(self, history, period=14):
        """Calculates a simplified RSI from deque history."""
        if len(history) < period + 1:
            return 50.0
        
        # Convert deque to list for slicing recent N candles
        prices = list(history)[-period-1:]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
        if losses == 0:
            return 100.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 1. Update Market History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Manage Portfolio (Exits & DCA)
        # Iterate over keys list to allow modifying dict size during loop
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            pos = self.positions[sym]
            hist = self.history[sym]
            
            # --- MUTATION: Volatility-Scaled Exit ---
            # Calculate local volatility
            volatility = 0.0
            if len(hist) > 10:
                volatility = statistics.stdev(hist) / (statistics.mean(hist) + 1e-9)
            
            # Dynamic Target: Base + (Vol * Scale). 
            # High vol -> Aim high (e.g. 2% + 1%*2 = 4%). Low vol -> Aim base.
            dynamic_target = max(self.min_roi, self.base_target + (volatility * 2.0))
            
            target_price = pos['avg_price'] * (1.0 + dynamic_target)
            
            # CHECK EXIT
            if curr_price >= target_price:
                # Absolute safety check for STOP_LOSS prevention
                proceeds = pos['qty'] * curr_price
                cost_basis = pos['qty'] * pos['avg_price']
                
                if proceeds > cost_basis:
                    self.balance += proceeds
                    del self.positions[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': pos['qty'],
                        'reason': ['VOL_TARGET_HIT']
                    }
            
            # CHECK DCA
            layer = pos['layer']
            if layer < len(self.dca_multipliers):
                # MUTATION: Elastic Grid
                # If vol is high (>1.5%), widen the grid to 1.5x to survive the shakeout
                grid_scalar = 1.5 if volatility > 0.015 else 1.0
                
                # Grid widens with depth: 2.5%, 5.0%, 7.5% ... scaled by vol
                step_pct = self.base_grid_step * (layer + 1) * grid_scalar
                trigger_price = pos['last_buy_price'] * (1.0 - step_pct)
                
                if curr_price < trigger_price:
                    multiplier = self.dca_multipliers[layer]
                    cost_to_buy = self.base_order_size * multiplier
                    
                    if self.balance >= cost_to_buy:
                        buy_qty = cost_to_buy / curr_price
                        
                        # Update Position
                        new_qty = pos['qty'] + buy_qty
                        new_cost_basis = (pos['qty'] * pos['avg_price']) + cost_to_buy
                        
                        pos['qty'] = new_qty
                        pos['avg_price'] = new_cost_basis / new_qty
                        pos['last_buy_price'] = curr_price
                        pos['layer'] += 1
                        
                        self.balance -= cost_to_buy
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{pos["layer"]}']
                        }

        # 3. Scan for New Entries
        # Strictly limited by solvency calculation
        if len(self.positions) < self.max_safe_positions:
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions: continue
                
                hist = self.history.get(sym)
                if not hist or len(hist) < 30: continue
                
                avg = statistics.mean(hist)
                std = statistics.stdev(hist)
                
                if std == 0: continue
                
                z = (price - avg) / std
                
                # Filter 1: Deep Value
                if z < self.entry_z:
                    # Filter 2: RSI Confirmation (Mutation)
                    # Prevents buying at the very beginning of a crash
                    rsi = self._calculate_rsi(hist)
                    if rsi < self.entry_rsi:
                        candidates.append({
                            'sym': sym,
                            'z': z,
                            'rsi': rsi,
                            'price': price
                        })
            
            # Sort by Z-score (most deviant first)
            candidates.sort(key=lambda x: x['z'])
            
            if candidates:
                best = candidates[0]
                cost = self.base_order_size
                
                if self.balance >= cost:
                    qty = cost / best['price']
                    self.balance -= cost
                    
                    self.positions[best['sym']] = {
                        'qty': qty,
                        'avg_price': best['price'],
                        'last_buy_price': best['price'],
                        'layer': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': best['sym'],
                        'amount': qty,
                        'reason': [f'Z_ENTRY_{best["z"]:.2f}']
                    }

        return {}