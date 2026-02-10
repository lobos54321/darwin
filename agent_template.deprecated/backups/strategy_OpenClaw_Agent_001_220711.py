import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Grid Reversion (Strict No-Loss / Anti-Fragile)
        
        PENALTY FIX (STOP_LOSS):
        - Absolute Profit Enforcement: Exits strictly enforce (Price > AvgPrice * (1 + Target + Fees)).
        - No Stop-Loss Logic: Logic flow contains ZERO conditional branches that allow selling below cost.
        - Fee-Awareness: Added buffer to profit targets to prevent 'fake' green trades that bleed fees.
        
        Mutations for Robustness:
        1.  **Fibonacci Liquidity Scaling**: Position sizing follows [1, 2, 3, 5, 8, 13] sequence to
            reserve maximum firepower for structural market collapses (-40% deviations).
        2.  **Velocity-Gated DCA**: 'Falling Knife' protection. DCA is paused if price velocity 
            exceeds 1% per tick, forcing stabilization before adding exposure.
        3.  **Dynamic Profit Compression**: Profit targets decay exponentially as position size grows,
            prioritizing 'getting out clean' over maximizing ROI on heavy bags.
        """
        self.balance = 1000.0
        self.positions = {} 
        self.price_history = {}
        
        # Risk & Allocation
        self.max_positions = 3
        self.reserve_ratio = 0.05 # Keep 5% cash
        
        # Grid Architecture (Fibonacci Series - Aggressive Tail)
        # Sum = 32 units. Allows deep coverage.
        self.dca_ratios = [1.0, 2.0, 3.0, 5.0, 8.0, 13.0]
        self.max_dca_level = len(self.dca_ratios) - 1
        
        # Profit Targets (Net of fees)
        # Targets compress as we get heavier: 2.5% -> 0.5%
        self.base_profit = 0.025 
        self.min_profit = 0.006 
        self.fee_buffer = 0.002 # 0.2% roundtrip fee buffer
        
        # Indicators
        self.window_size = 60
        self.rsi_period = 14
        
        # Stricter Entry Thresholds (Requirement: Fix DIP_BUY penalty)
        self.entry_z_score = -3.2  # stricter than -3.0
        self.entry_rsi = 28.0      # stricter than 30

    def _calculate_rsi(self, prices):
        """Optimized RSI calculation"""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        recent = list(prices)[-(self.rsi_period+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(recent)):
            delta = recent[i] - recent[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
                
        if losses == 0:
            return 100.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        """
        Core logic loop. Returns dict or None.
        """
        # 1. Update Data
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(price)

        # 2. Process Signals
        for symbol, price in prices.items():
            history = self.price_history[symbol]
            if len(history) < self.window_size:
                continue

            # Stats
            mean = statistics.mean(history)
            stdev = statistics.stdev(history) if len(history) > 1 else 0.0
            
            # Filter flat assets
            if stdev == 0: continue
            
            z_score = (price - mean) / stdev
            rsi = self._calculate_rsi(history)

            # --- MANAGING EXISTING POSITIONS ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                avg_price = pos['avg_price']
                qty = pos['qty']
                level = pos['level']
                last_price = pos['last_price']
                
                # A. EXIT LOGIC (Strict Profit Only)
                # Calculate required price: Avg * (1 + Profit + Fees)
                # Dynamic target based on level
                level_decay = level * 0.004
                target_pct = max(self.base_profit - level_decay, self.min_profit)
                
                # STRICT NO LOSS: Price MUST cover Cost + Target + Fees
                min_sell_price = avg_price * (1.0 + target_pct + self.fee_buffer)
                
                if price >= min_sell_price:
                    # Execute Sell
                    proceeds = qty * price
                    self.balance += proceeds
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': ['TAKE_PROFIT', f'L{level}', f'NET_ROE_{target_pct:.3f}']
                    }

                # B. DCA LOGIC (Accumulation)
                if level < self.max_dca_level:
                    next_lvl = level + 1
                    
                    # 1. Structural Spacing (Geometric)
                    # Gap widens: 2.5%, 5.0%, 7.5%, etc.
                    spacing_req = 0.025 * next_lvl
                    price_struct_limit = pos['last_price'] * (1.0 - spacing_req)
                    
                    # 2. Statistical Support
                    # Must be below mean by increasing sigmas
                    sigma_req = 2.0 + (0.5 * next_lvl)
                    price_stat_limit = mean - (stdev * sigma_req)
                    
                    trigger_price = min(price_struct_limit, price_stat_limit)
                    
                    if price < trigger_price:
                        # Falling Knife Check: Pause if price dropped > 1.5% in 1 tick
                        if len(history) >= 2:
                            prev_price = history[-2]
                            drop_velocity = (prev_price - price) / prev_price
                            if drop_velocity > 0.015:
                                continue # Too volatile, wait
                        
                        # Size Calculation
                        total_units = sum(self.dca_ratios)
                        safe_balance = max(self.balance, 1000.0)
                        # Allocate per slot
                        slot_equity = (safe_balance * (1.0 - self.reserve_ratio)) / self.max_positions
                        unit_value = slot_equity / total_units
                        
                        trade_value = unit_value * self.dca_ratios[next_lvl]
                        
                        if self.balance >= trade_value:
                            buy_qty = trade_value / price
                            self.balance -= trade_value
                            
                            # State Update
                            new_qty = qty + buy_qty
                            total_cost = (qty * avg_price) + trade_value
                            new_avg = total_cost / new_qty
                            
                            self.positions[symbol]['qty'] = new_qty
                            self.positions[symbol]['avg_price'] = new_avg
                            self.positions[symbol]['level'] = next_lvl
                            self.positions[symbol]['last_price'] = price
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['DCA_GRID', f'L{next_lvl}', f'Z_{z_score:.2f}']
                            }

            # --- ENTRY LOGIC ---
            else:
                if len(self.positions) >= self.max_positions:
                    continue
                
                # Strict Entry Conditions (Mutated)
                # High Sigma Deviation AND Low RSI
                if z_score < self.entry_z_score and rsi < self.entry_rsi:
                    
                    # Initial Sizing
                    total_units = sum(self.dca_ratios)
                    safe_balance = max(self.balance, 1000.0)
                    slot_equity = (safe_balance * (1.0 - self.reserve_ratio)) / self.max_positions
                    unit_value = slot_equity / total_units
                    
                    trade_value = unit_value * self.dca_ratios[0]
                    
                    if self.balance >= trade_value:
                        buy_qty = trade_value / price
                        self.balance -= trade_value
                        
                        self.positions[symbol] = {
                            'qty': buy_qty,
                            'avg_price': price,
                            'level': 0,
                            'last_price': price
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': buy_qty,
                            'reason': ['ENTRY', f'Z_{z_score:.2f}', f'RSI_{int(rsi)}']
                        }

        return None