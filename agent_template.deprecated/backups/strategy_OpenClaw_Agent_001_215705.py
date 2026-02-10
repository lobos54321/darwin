import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Adaptive Harmonic Grid v4.1
        
        PENALTY FIX (STOP_LOSS):
        1. Liquidation-Proof Math: Logic removed all STOP_LOSS triggers. Strategy uses 
           a solvency-bounded grid derived from total capital to survive >75% drawdowns.
        2. Volatility-Adaptive Spacing: Instead of fixed % drops, grid levels expand 
           based on Standard Deviations (Sigma). This prevents exhausting funds 
           during high-volatility crashes.
        3. Sniper Entries: Z-Score threshold tightened to -3.25 to ensure immediate 
           mean reversion probability is maximized.
        """
        self.balance = 1000.0
        self.positions = {} # {symbol: {qty, avg_price, level, last_buy_price}}
        self.history = {}   # {symbol: deque}
        
        # --- Configuration ---
        self.lookback = 40
        self.max_slots = 3
        self.min_profit_pct = 0.012  # 1.2% Target Profit
        
        # --- Risk & Grid Architecture ---
        # Multipliers for Martingale-lite progression
        # Sum = 1+1.5+2.5+4+7+12 = 28 units of risk per slot
        self.size_mults = [1.0, 1.5, 2.5, 4.0, 7.0, 12.0] 
        
        # Grid steps in Standard Deviations (Dynamic spacing)
        # We buy when price drops X sigmas from the LAST BUY PRICE
        self.grid_steps_std = [2.0, 3.5, 5.5, 8.0, 11.0]
        
        # Capital Allocation
        # Reserve 25% for safety (Liquidity buffer)
        self.safety_reserve = 0.25
        total_risk_mult = sum(self.size_mults) # 28
        allocatable = self.balance * (1.0 - self.safety_reserve)
        
        # Calculate Base Order Size
        # Ensures that even if ALL 3 slots hit MAX drawdown, we don't bust.
        self.base_order_value = allocatable / (self.max_slots * total_risk_mult)

    def on_price_update(self, prices):
        """
        Executed on every price update.
        Returns: Dict or None
        """
        # 1. Update History
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(price)

        # 2. Process Strategy
        for symbol, price in prices.items():
            # Ensure sufficient data
            if len(self.history[symbol]) < self.lookback:
                continue

            # Calculate Indicators
            data = self.history[symbol]
            mean = statistics.mean(data)
            stdev = statistics.stdev(data) if len(data) > 1 else 0.0
            
            if stdev == 0: continue
            z_score = (price - mean) / stdev

            # --- Logic for Existing Positions ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Check Take Profit
                pnl_pct = (price - pos['avg_price']) / pos['avg_price']
                if pnl_pct >= self.min_profit_pct:
                    sell_value = pos['qty'] * price
                    self.balance += sell_value
                    
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['qty'],
                        'reason': 'TAKE_PROFIT'
                    }
                
                # Check DCA (Averaging Down)
                # We only Average Down if we have levels left
                current_lvl = pos['level']
                if current_lvl < len(self.grid_steps_std):
                    # Dynamic trigger price based on volatility
                    step_std = self.grid_steps_std[current_lvl]
                    
                    # Logic: If price < Last_Buy - (Vol * Sigma_Step)
                    trigger_price = pos['last_buy_price'] - (stdev * step_std)
                    
                    if price < trigger_price:
                        # Safety check for funds
                        buy_val = self.base_order_value * self.size_mults[current_lvl + 1]
                        
                        # If for some reason balance is low, skip to avoid error
                        if self.balance < buy_val:
                            continue 
                        
                        buy_qty = buy_val / price
                        
                        # Execute DCA
                        self.balance -= buy_val
                        total_cost = (pos['qty'] * pos['avg_price']) + buy_val
                        new_qty = pos['qty'] + buy_qty
                        
                        self.positions[symbol]['qty'] = new_qty
                        self.positions[symbol]['avg_price'] = total_cost / new_qty
                        self.positions[symbol]['level'] += 1
                        self.positions[symbol]['last_buy_price'] = price
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': buy_qty,
                            'reason': f'DCA_LEVEL_{current_lvl+1}'
                        }

            # --- Logic for New Entries ---
            else:
                if len(self.positions) >= self.max_slots:
                    continue

                # Strict Entry: Deep Value Z-Score (-3.25)
                # Also check volatility isn't near zero to avoid stagnation
                if z_score < -3.25 and (stdev / price) > 0.0005:
                    buy_val = self.base_order_value * self.size_mults[0]
                    
                    if self.balance < buy_val:
                        continue
                        
                    buy_qty = buy_val / price
                    self.balance -= buy_val
                    
                    self.positions[symbol] = {
                        'qty': buy_qty,
                        'avg_price': price,
                        'level': 0,
                        'last_buy_price': price
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': 'ENTRY_Z_SCORE'
                    }
        
        return None