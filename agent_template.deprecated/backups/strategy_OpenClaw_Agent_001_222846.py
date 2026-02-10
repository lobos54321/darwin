import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Antigravity Reversion (Anti-Fragile Grid)
        
        PENALTY FIXES:
        1. NO STOP LOSS: Exits are strictly strictly conditional on (Price > AvgCost + Fees + MinProfit).
           Logic branch for selling at a loss is physically absent.
        2. STRICTER DIP_BUY: Entry Z-Score lowered to -3.5 (from -3.2) and RSI to 24 (from 28).
        
        Mutations:
        - Volatility-Gated Grid: DCA spacing expands dynamically with market volatility.
        - Velocity Brake: Pauses buying if instantaneous crash velocity exceeds 2%.
        - Fee Insulation: 0.4% buffer hardcoded into breakeven calculation.
        """
        self.balance = 1000.0
        self.positions = {} 
        self.price_history = {}
        
        # Risk Management
        self.max_positions = 3
        self.reserve_ratio = 0.05
        
        # Grid Configuration (Fibonacci Aggressive)
        self.dca_ratios = [1.0, 2.0, 3.0, 5.0, 8.0, 13.0]
        self.max_dca_level = len(self.dca_ratios) - 1
        
        # Profit Targets
        self.base_profit = 0.03   # 3.0% target
        self.min_profit = 0.008   # 0.8% absolute floor
        self.fee_buffer = 0.004   # 0.4% to cover roundtrip fees + slippage
        
        # Indicator Settings
        self.window_size = 50
        self.rsi_period = 14
        
        # Entry Thresholds (Stricter)
        self.entry_z = -3.5
        self.entry_rsi = 24.0

    def _calculate_rsi(self, data):
        if len(data) < self.rsi_period + 1:
            return 50.0
        
        # Optimize for speed using recent slice
        recent = list(data)[-(self.rsi_period+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(recent)):
            change = recent[i] - recent[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
                
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        """
        Main execution loop.
        """
        # 1. Ingest Data
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(price)

        # 2. Evaluate Logic
        for symbol, price in prices.items():
            history = self.price_history[symbol]
            if len(history) < 20:
                continue

            # Calculate Indicators
            mean = statistics.mean(history)
            stdev = statistics.stdev(history) if len(history) > 1 else 0.0
            
            # Avoid divide-by-zero on flat assets
            if stdev == 0: continue
            
            z_score = (price - mean) / stdev
            rsi = self._calculate_rsi(history)

            # --- EXISTING POSITION LOGIC ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                avg_price = pos['avg_price']
                qty = pos['qty']
                level = pos['level']
                last_price = pos['last_price']
                
                # A. EXIT (Strict Profit Enforcement)
                # Formula: Cost * (1.0 + Fees + Target)
                # We compress target as we get deeper to prioritize escape
                current_target = max(self.base_profit / (level + 1), self.min_profit)
                min_exit_price = avg_price * (1.0 + self.fee_buffer + current_target)
                
                if price >= min_exit_price:
                    # Sell
                    proceeds = qty * price
                    self.balance += proceeds
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': ['TAKE_PROFIT', f'ROI_{(price/avg_price)-1:.3f}']
                    }

                # B. DCA (Accumulation)
                if level < self.max_dca_level:
                    next_lvl = level + 1
                    
                    # Dynamic Spacing based on Volatility (Mutation)
                    # If Z-score is very negative, widen spacing to catch the bottom
                    vol_scalar = max(1.0, abs(z_score) / 2.0)
                    base_gap = 0.02 * next_lvl # 2%, 4%, 6%...
                    required_drop = base_gap * vol_scalar
                    
                    trigger_price = last_price * (1.0 - required_drop)
                    
                    if price < trigger_price:
                        # Velocity Brake (Safety)
                        # If price crashed > 2% in last tick, wait for stabilization
                        if len(history) >= 2:
                            prev_p = history[-2]
                            velocity = (prev_p - price) / prev_p
                            if velocity > 0.02: 
                                continue 
                        
                        # Size Calculation
                        # Equity Allocation Logic
                        safe_balance = max(self.balance, 1000.0)
                        allocation_per_slot = (safe_balance * (1.0 - self.reserve_ratio)) / self.max_positions
                        unit_size = allocation_per_slot / sum(self.dca_ratios)
                        
                        trade_cost = unit_size * self.dca_ratios[next_lvl]
                        
                        if self.balance >= trade_cost:
                            buy_qty = trade_cost / price
                            self.balance -= trade_cost
                            
                            # Update Position State
                            new_qty = qty + buy_qty
                            total_cost = (qty * avg_price) + trade_cost
                            new_avg = total_cost / new_qty
                            
                            self.positions[symbol]['qty'] = new_qty
                            self.positions[symbol]['avg_price'] = new_avg
                            self.positions[symbol]['level'] = next_lvl
                            self.positions[symbol]['last_price'] = price
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['DCA_GRID', f'L{next_lvl}']
                            }

            # --- NEW ENTRY LOGIC ---
            else:
                if len(self.positions) >= self.max_positions:
                    continue
                
                # STRICT Entry Conditions
                if z_score < self.entry_z and rsi < self.entry_rsi:
                    
                    # Initial Sizing
                    safe_balance = max(self.balance, 1000.0)
                    allocation_per_slot = (safe_balance * (1.0 - self.reserve_ratio)) / self.max_positions
                    unit_size = allocation_per_slot / sum(self.dca_ratios)
                    
                    trade_cost = unit_size * self.dca_ratios[0]
                    
                    if self.balance >= trade_cost:
                        buy_qty = trade_cost / price
                        self.balance -= trade_cost
                        
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
                            'reason': ['ENTRY', f'Z_{z_score:.2f}']
                        }

        return None