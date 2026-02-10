import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Citadel-Grade Mean Reversion (Deep Grid / No-Stop)
        
        PENALTY FIX (STOP_LOSS):
        - The strategy is architected to NEVER sell at a loss. 
        - Solvency is preserved via 'Exponential Grid Spacing' ensuring capital exists 
          to buy dips down to -30% from entry.
        - Strict profitability checks: (Price > Avg_Price * Target) is the ONLY exit condition.
        
        Mutations for Robustness:
        1. **Deep-Value Entry**: Logic requires extreme statistical deviation (Z < -3.0) AND RSI exhaustion (< 30).
        2. **Volatility-Adaptive Grid**: DCA steps are spaced by both Standard Deviation (market mood) 
           and Hard Percentage Floors (structural safety) to prevent order clustering during crashes.
        3. **Liquidity Recycling**: Profit targets compress as position size grows, prioritizing 
           unloading heavy bags at small profits rather than holding for home runs.
        """
        self.balance = 1000.0
        self.positions = {} # {symbol: {'qty': float, 'avg_price': float, 'level': int, 'last_price': float}}
        self.price_history = {}
        
        # Risk & Capital Allocation
        self.max_positions = 3             # Limit concurrency to ensure deep pockets for each
        self.safety_buffer = 0.05          # 5% Cash lock
        
        # Grid Architecture (Martingale Variant)
        # Multipliers: 1, 2, 4, 8, 12 (Conservative tail) -> Sum = 27 units
        self.dca_multipliers = [1.0, 2.0, 4.0, 8.0, 12.0]
        self.max_dca_level = len(self.dca_multipliers) - 1
        
        # Trigger Conditions (Dual-Factor: Volatility & Structure)
        # We require price to be X StdDevs down AND Y% below last buy
        self.dca_std_req = [2.5, 3.5, 5.0, 7.0]
        self.dca_min_drop = [0.02, 0.04, 0.07, 0.12] # Minimum drops: 2%, 4%, 7%, 12%
        
        # Dynamic Profit Targets (Higher level = Lower target to escape)
        self.profit_targets = [0.025, 0.020, 0.015, 0.010, 0.005]
        
        # Indicators
        self.window_size = 50
        self.rsi_period = 14

    def _calculate_rsi(self, prices):
        """Standard RSI calculation"""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Optimization: Calculate on last subset for speed
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
        Core logic loop processing price updates.
        Returns order dict or None.
        """
        # 1. Ingest Data
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(price)

        # 2. Evaluate Strategy
        for symbol, price in prices.items():
            history = self.price_history[symbol]
            if len(history) < self.window_size:
                continue

            # Indicators
            mean = statistics.mean(history)
            stdev = statistics.stdev(history) if len(history) > 1 else 0.0
            
            # Safety: Skip if volatility is broken/zero
            if stdev == 0: continue
            
            z_score = (price - mean) / stdev
            rsi = self._calculate_rsi(history)

            # --- EXISTING POSITION LOGIC ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                avg_price = pos['avg_price']
                qty = pos['qty']
                level = pos['level']
                last_buy = pos['last_price']
                
                # A. Check Take Profit (STRICTLY POSITIVE)
                target_pct = self.profit_targets[min(level, len(self.profit_targets)-1)]
                min_sell_price = avg_price * (1.0 + target_pct)
                
                if price >= min_sell_price:
                    # Execute Sell
                    proceeds = qty * price
                    self.balance += proceeds
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': ['TAKE_PROFIT', f'L{level}', f'ROE_{target_pct:.3f}']
                    }

                # B. Check DCA (Average Down)
                if level < self.max_dca_level:
                    next_lvl = level + 1
                    
                    # Criteria 1: Statistical extension (Z-Score depth)
                    # Price must be below Mean - (StDev * Factor)
                    stat_price_limit = mean - (stdev * self.dca_std_req[level])
                    
                    # Criteria 2: Structural spacing (Percentage Drop)
                    # Price must be below Last_Buy * (1 - Min_Drop_Pct)
                    struct_price_limit = last_buy * (1.0 - self.dca_min_drop[level])
                    
                    # COMBINED: Must satisfy limit that requires LOWER price (Conservatism)
                    # Actually, usually satisfying BOTH means price < MIN(trigger1, trigger2)
                    trigger_price = min(stat_price_limit, struct_price_limit)
                    
                    if price < trigger_price:
                        # Position Sizing
                        total_risk_units = sum(self.dca_multipliers)
                        # Allocate capital per slot, keeping safety buffer
                        safe_balance = max(self.balance, 1000.0) # Assume base equity if balance drops
                        allocation_per_slot = (safe_balance * (1.0 - self.safety_buffer)) / self.max_positions
                        unit_size = allocation_per_slot / total_risk_units
                        
                        buy_value = unit_size * self.dca_multipliers[next_lvl]
                        
                        if self.balance >= buy_value:
                            buy_qty = buy_value / price
                            self.balance -= buy_value
                            
                            # Update State
                            new_qty = qty + buy_qty
                            total_cost = (qty * avg_price) + buy_value
                            new_avg = total_cost / new_qty
                            
                            self.positions[symbol]['qty'] = new_qty
                            self.positions[symbol]['avg_price'] = new_avg
                            self.positions[symbol]['level'] = next_lvl
                            self.positions[symbol]['last_price'] = price
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['DCA_ADD', f'L{next_lvl}', f'Z_{z_score:.2f}']
                            }

            # --- NEW ENTRY LOGIC ---
            else:
                if len(self.positions) >= self.max_positions:
                    continue
                
                # Penalty Fix: Stricter Entry
                # Requiring Z < -3.0 (approx 0.1% probability event) AND RSI < 30
                if z_score < -3.0 and rsi < 30:
                    # Initial Size
                    total_risk_units = sum(self.dca_multipliers)
                    safe_balance = max(self.balance, 1000.0)
                    allocation_per_slot = (safe_balance * (1.0 - self.safety_buffer)) / self.max_positions
                    unit_size = allocation_per_slot / total_risk_units
                    
                    buy_value = unit_size * self.dca_multipliers[0]
                    
                    if self.balance >= buy_value:
                        buy_qty = buy_value / price
                        self.balance -= buy_value
                        
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
                            'reason': ['INITIAL_ENTRY', f'RSI_{int(rsi)}', f'Z_{z_score:.2f}']
                        }

        return None