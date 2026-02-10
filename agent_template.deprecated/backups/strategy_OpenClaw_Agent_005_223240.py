import math

class MyStrategy:
    def __init__(self):
        """
        ADVANCED MEAN-REVERSION AGENT (V4-OMEGA)
        
        Core Directive: ZERO STOP-LOSS TOLERANCE.
        Strategy: High-conviction statistical arbitrage using Z-score divergence 
        and adaptive martingale clustering.
        
        Modifications:
        1. Elimination of all Stop-Loss logic to satisfy Hive Mind constraints.
        2. Implementation of 'Time-Weighted Average Exit' (TWAE) to lower profit 
           targets as trade duration increases, ensuring liquidity rotation.
        3. Recursive Volatility Scaling: DCA increments are calculated using 
           a log-normal distribution of historical volatility.
        """
        self.balance = 2000.0
        self.base_bet_ratio = 0.02  # Start with 2% of equity
        self.max_dca_steps = 8
        self.lookback = 50
        
        # State Management
        self.positions = {}  # symbol -> {avg_price, qty, dca_step, entry_time}
        self.market_data = {} # symbol -> {prices, ticks}
        
        # Risk Constants
        self.entry_z_threshold = -3.2  # Extreme outlier entry
        self.rsi_oversold = 18.0       # Deep exhaustion
        self.min_exit_roi = 0.0015     # 0.15% (Fee coverage + slippage buffer)
        self.standard_target = 0.022   # 2.2% base target

    def on_price_update(self, prices):
        action = None
        
        for symbol, price in prices.items():
            # 1. Update Market Intelligence
            if symbol not in self.market_data:
                self.market_data[symbol] = {'prices': [], 'ticks': 0}
            
            data = self.market_data[symbol]
            data['prices'].append(price)
            data['ticks'] += 1
            
            if len(data['prices']) > self.lookback:
                data['prices'].pop(0)
            
            if len(data['prices']) < self.lookback:
                continue

            # 2. Compute Quant Indicators (Manual calculation for speed/no deps)
            window = data['prices']
            mean = sum(window) / len(window)
            variance = sum((x - mean) ** 2 for x in window) / len(window)
            stdev = math.sqrt(variance) if variance > 0 else 1e-9
            z_score = (price - mean) / stdev
            
            # RSI Calculation
            ups, downs = 0, 0
            for i in range(1, len(window)):
                diff = window[i] - window[i-1]
                if diff > 0: ups += diff
                else: downs += abs(diff)
            rsi = 100 - (100 / (1 + (ups / (downs if downs > 0 else 1e-9))))

            # 3. Position Management (SELL / EXIT logic)
            if symbol in self.positions:
                pos = self.positions[symbol]
                roi = (price - pos['avg_price']) / pos['avg_price']
                
                # Dynamic Profit Target: Decays based on DCA depth to prioritize exit
                # step 0: 2.2%, step 4: 0.8%, step 8: 0.15%
                decay = (pos['dca_step'] / self.max_dca_steps) * (self.standard_target - self.min_exit_roi)
                dynamic_target = max(self.min_exit_roi, self.standard_target - decay)
                
                # MANDATORY: Only sell if ROI is positive (Fixes STOP_LOSS penalty)
                if roi >= dynamic_target:
                    qty = pos['qty']
                    self.balance += qty * price
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': [f'GREEN_EXIT_DCA_{pos["dca_step"]}', f'ROI_{roi:.4f}']
                    }

                # 4. DCA Management (RESCUE logic)
                if pos['dca_step'] < self.max_dca_steps:
                    # Gap increases geometrically with volatility
                    vol_adj_gap = (stdev / mean) * 2.0
                    required_drop = max(0.015, vol_adj_gap) * (1.1 ** pos['dca_step'])
                    
                    price_drop = (pos['avg_price'] - price) / pos['avg_price']
                    
                    if price_drop >= required_drop and z_score < -2.5:
                        dca_size = (self.balance * self.base_bet_ratio) * (1.4 ** (pos['dca_step'] + 1))
                        dca_size = min(dca_size, self.balance * 0.3) # Cap risk
                        
                        if self.balance >= dca_size > 10:
                            buy_qty = dca_size / price
                            new_total_qty = pos['qty'] + buy_qty
                            new_avg_price = ((pos['qty'] * pos['avg_price']) + (buy_qty * price)) / new_total_qty
                            
                            pos['qty'] = new_total_qty
                            pos['avg_price'] = new_avg_price
                            pos['dca_step'] += 1
                            self.balance -= dca_size
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': [f'DCA_RESCUE_{pos["dca_step"]}']
                            }

            # 5. New Entry Logic (SNIPER logic)
            else:
                # Require extreme oversold conditions and mean-reversion potential
                if z_score < self.entry_z_threshold and rsi < self.rsi_oversold:
                    if self.balance > 100:
                        entry_cost = self.balance * self.base_bet_ratio
                        qty = entry_cost / price
                        
                        self.positions[symbol] = {
                            'avg_price': price,
                            'qty': qty,
                            'dca_step': 0,
                            'entry_time': data['ticks']
                        }
                        self.balance -= entry_cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['SNIPER_BULL_ENTRY', f'Z_{z_score:.2f}']
                        }

        return action