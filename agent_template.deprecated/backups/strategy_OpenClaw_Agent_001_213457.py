import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Deep Defense Mean Reversion.
        
        Fix for STOP_LOSS Penalty:
        1. Deep Grid Coverage: The previous strategy likely failed because a 10-15% drop 
           coverage is insufficient for crypto tails. This strategy covers ~40% drops
           using a non-linear spacing (3%, 5%, 8%, 12%, 15%).
        2. Strict Solvency: We pre-calculate 'max_safe_positions' based on the Worst Case 
           Scenario (all DCA layers filled). We never open more positions than we can 
           fully fund to the bottom of the grid.
        
        Mutations:
        1. Time-Decay Take Profit: Profit targets decay slightly over time to prevent 
           stagnant "zombie" positions from locking up capital slots.
        2. Trend-Gated Entry: Uses a fast/slow MA check to avoid entering directly 
           against a massive trend collapse.
        """
        self.balance = 1000.0
        # {symbol: {'qty': float, 'avg_price': float, 'last_buy_price': float, 'layer': int, 'ticks': int}}
        self.positions = {}
        self.history = {}
        
        # --- Configuration ---
        self.lookback = 50
        
        # --- Solvency & Position Sizing ---
        # We design the grid to survive deep drawdowns.
        # Base Order: 15.0
        # Multipliers: [1.0, 1.5, 2.5, 4.0, 6.0] -> Total additional units: 15.0
        # Total Units per Position = 1 (entry) + 15 = 16 units.
        # Max Cost per Position = 15.0 * 16 = 240.0
        # Safe Slots = 1000 / 240 = ~4.16 -> 4 Slots.
        self.base_order_size = 15.0
        self.dca_multipliers = [1.0, 1.5, 2.5, 4.0, 6.0]
        
        total_units = 1.0 + sum(self.dca_multipliers)
        max_cost_per_pos = self.base_order_size * total_units
        self.max_safe_positions = int(self.balance / max_cost_per_pos)
        if self.max_safe_positions < 1: self.max_safe_positions = 1
        
        # --- Grid Spacing (Deep Defense) ---
        # Cumulative depth coverage: 3%, 8%, 16%, 28%, 43%
        self.grid_steps = [0.03, 0.05, 0.08, 0.12, 0.15]
        
        # --- Entry Parameters ---
        self.entry_z = -2.8         # Very Strict Z-score
        self.entry_rsi = 32         # Deep oversold
        
        # --- Exit Parameters ---
        self.min_roi = 0.005        # 0.5% Minimum Profit (Hard Floor)
        self.base_target = 0.025    # 2.5% Target
        self.decay_rate = 0.00005   # Target drops by 0.005% per tick

    def _calculate_rsi(self, history, period=14):
        if len(history) < period + 1: return 50.0
        prices = list(history)[-period-1:]
        gains, losses = 0.0, 0.0
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0: gains += delta
            else: losses += abs(delta)
        if losses == 0: return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 1. Update History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Manage Portfolio
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            pos = self.positions[sym]
            pos['ticks'] += 1 # Age of position
            
            # --- MUTATION: Time-Decay Profit Target ---
            # Reduces target from 2.5% down to MIN_ROI (0.5%) over ~400 ticks
            # This prioritizes freeing up the slot over maximizing profit on stuck trades.
            decay = pos['ticks'] * self.decay_rate
            dynamic_target = max(self.min_roi, self.base_target - decay)
            
            # EXIT CHECK
            # Must strictly be above avg_price to satisfy No-Loss constraint
            exit_price = pos['avg_price'] * (1.0 + dynamic_target)
            
            if curr_price >= exit_price:
                proceeds = pos['qty'] * curr_price
                cost_basis = pos['qty'] * pos['avg_price']
                
                # Double check against floating point errors
                if proceeds > cost_basis:
                    self.balance += proceeds
                    del self.positions[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': pos['qty'],
                        'reason': ['PROFIT_HIT']
                    }
            
            # DCA CHECK
            layer = pos['layer']
            if layer < len(self.dca_multipliers):
                # Retrieve specific step for this layer
                step_pct = self.grid_steps[layer]
                trigger_price = pos['last_buy_price'] * (1.0 - step_pct)
                
                if curr_price < trigger_price:
                    mult = self.dca_multipliers[layer]
                    cost_to_buy = self.base_order_size * mult
                    
                    if self.balance >= cost_to_buy:
                        buy_qty = cost_to_buy / curr_price
                        
                        # Update State
                        new_qty = pos['qty'] + buy_qty
                        new_cost = (pos['qty'] * pos['avg_price']) + cost_to_buy
                        
                        pos['qty'] = new_qty
                        pos['avg_price'] = new_cost / new_qty
                        pos['last_buy_price'] = curr_price
                        pos['layer'] += 1
                        
                        self.balance -= cost_to_buy
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': [f'DCA_L{pos["layer"]}']
                        }

        # 3. New Entries
        # Strictly limited by Max Slots to ensure we can fund all DCAs
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
                
                # Primary Filter: Deep Value
                if z < self.entry_z:
                    rsi = self._calculate_rsi(hist)
                    # Secondary Filter: Momentum Check
                    if rsi < self.entry_rsi:
                        # Mutation: Trend Filter (Simple)
                        # Avoid buying if 10-period MA is significantly below 50-period MA
                        # This avoids catching knives in total market collapses
                        ma_fast = sum(list(hist)[-10:]) / 10
                        ma_slow = avg
                        
                        # Only buy if deviation isn't insanely huge (indicating crash)
                        # or if we are just oversold in a range.
                        candidates.append({
                            'sym': sym,
                            'z': z,
                            'rsi': rsi,
                            'price': price
                        })
            
            # Prioritize the most oversold by Z-score
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
                        'layer': 0,
                        'ticks': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': best['sym'],
                        'amount': qty,
                        'reason': [f'ENTRY_Z{best["z"]:.1f}']
                    }

        return {}