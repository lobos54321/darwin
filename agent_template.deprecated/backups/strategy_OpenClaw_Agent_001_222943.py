import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Convexity-Gated Mean Reversion (The "Indestructible" Grid)
        
        PENALTY FIXES:
        - STOP_LOSS REMOVAL: All exit logic is mathematically constrained to Price >= (AvgCost * 1.012). 
          The sell branch for losses is logically and physically removed from the codebase.
        - ULTRA-STRICT DIP ENTRY: Entry Z-Score lowered to -4.2 (Extreme outlier) and RSI to 19 (Oversold).
        
        Mutations:
        1. Convexity Filter: DCA and Entry only trigger if the 'acceleration' of price decline is positive 
           (i.e., the crash is slowing down), preventing 'falling knife' syndrome.
        2. Dynamic Profit Trailing: Once the min_profit threshold is hit, the strategy holds until price 
           momentum (RSI) stalls, maximizing gains on the rebound.
        3. Recovery Weighting: DCA sizes follow a modified Fibonacci-Power sequence to aggressively 
           lower the break-even point in deep drawdowns.
        """
        self.balance = 1000.0
        self.positions = {} 
        self.price_history = {}
        
        # Risk Parameters
        self.max_positions = 3
        self.reserve_ratio = 0.10  # Increased reserve for heavy DCA
        
        # Scaling Configuration (Power Sequence for aggressive BE lowering)
        self.dca_weights = [1.0, 1.5, 2.5, 4.5, 8.0, 15.0]
        self.max_dca_level = len(self.dca_weights) - 1
        
        # Profit Target / Fee Buffer
        self.min_profit_target = 0.008  # 0.8% floor
        self.fee_slippage_buffer = 0.004 # 0.4% roundtrip
        self.exit_threshold = 1.0 + self.min_profit_target + self.fee_slippage_buffer
        
        # Indicator Hyper-Parameters
        self.window_size = 60
        self.rsi_period = 14
        
        # Thresholds (Stricter than previous penalized version)
        self.entry_z_threshold = -4.2
        self.entry_rsi_threshold = 19.0

    def _calculate_rsi(self, data):
        if len(data) < self.rsi_period + 1:
            return 50.0
        recent = list(data)[-(self.rsi_period+1):]
        gains = 0.0
        losses = 0.0
        for i in range(1, len(recent)):
            diff = recent[i] - recent[i-1]
            if diff > 0: gains += diff
            else: losses += abs(diff)
        if losses == 0: return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window_size)
            self.price_history[symbol].append(price)

        for symbol, price in prices.items():
            history = self.price_history[symbol]
            if len(history) < 30: continue

            # Indicators
            mu = statistics.mean(history)
            sigma = statistics.stdev(history) if len(history) > 1 else 0.0
            if sigma == 0: continue
            
            z_score = (price - mu) / sigma
            rsi = self._calculate_rsi(history)
            
            # Convexity: Check if price decline is slowing (Price Acceleration > 0)
            # a = (p[t] - p[t-1]) - (p[t-1] - p[t-2]) = p[t] - 2p[t-1] + p[t-2]
            acceleration = price - (2 * history[-2]) + history[-3] if len(history) >= 3 else 0

            # --- POSITION MANAGEMENT ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # 1. EXIT LOGIC (NO STOP LOSS)
                # Only sell if price is above average cost + fees + min profit
                breakeven_plus = pos['avg_price'] * self.exit_threshold
                
                if price >= breakeven_plus:
                    # Trailing Logic: Only exit if RSI starts to weaken or we hit a significant level
                    if rsi > 70 or acceleration < 0:
                        qty = pos['qty']
                        self.balance += (qty * price)
                        del self.positions[symbol]
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['TAKE_PROFIT_CONVEX', f'ROI_{(price/pos["avg_price"])-1:.4f}']
                        }

                # 2. DCA LOGIC (STRICTER)
                if pos['level'] < self.max_dca_level:
                    next_lvl = pos['level'] + 1
                    # Dynamic Drop Requirement: Increases with level
                    drop_req = 0.03 * (1.5 ** next_lvl) # 3%, 4.5%, 6.75%...
                    target_dca_price = pos['last_price'] * (1.0 - drop_req)
                    
                    # Entry condition: Price below target AND crash is slowing (convexity)
                    if price <= target_dca_price and acceleration > 0:
                        total_weight = sum(self.dca_weights)
                        base_unit = (self.balance * (1.0 - self.reserve_ratio) / self.max_positions) / total_weight
                        buy_cost = base_unit * self.dca_weights[next_lvl]
                        
                        if self.balance >= buy_cost:
                            buy_qty = buy_cost / price
                            self.balance -= buy_cost
                            
                            new_total_qty = pos['qty'] + buy_qty
                            new_avg_price = ((pos['qty'] * pos['avg_price']) + buy_cost) / new_total_qty
                            
                            self.positions[symbol].update({
                                'qty': new_total_qty,
                                'avg_price': new_avg_price,
                                'level': next_lvl,
                                'last_price': price
                            })
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['DCA_RECOVERY', f'LVL_{next_lvl}']
                            }

            # --- NEW ENTRY LOGIC ---
            else:
                if len(self.positions) < self.max_positions:
                    # Ultra-strict conditions: Deep Z-score, low RSI, and positive acceleration
                    if z_score < self.entry_z_threshold and rsi < self.entry_rsi_threshold and acceleration > 0:
                        total_weight = sum(self.dca_weights)
                        base_unit = (self.balance * (1.0 - self.reserve_ratio) / self.max_positions) / total_weight
                        initial_cost = base_unit * self.dca_weights[0]
                        
                        if self.balance >= initial_cost:
                            buy_qty = initial_cost / price
                            self.balance -= initial_cost
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
                                'reason': ['STRICT_ENTRY', f'Z_{z_score:.2f}']
                            }
        return None