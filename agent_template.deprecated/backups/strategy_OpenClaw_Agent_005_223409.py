import math

class MyStrategy:
    def __init__(self):
        """
        QUANTUM-REVERSION ENGINE (V5-ALPHA)
        
        Strategy: Pure Bull-Accumulation with Zero Stop-Loss (ZSL) Protocol.
        Constraint: Never sell below average cost.
        Mechanism: Deep-value sniper entries followed by volatility-adjusted DCA 
                   to collapse the average price during adverse moves.
        """
        self.balance = 2000.0
        self.base_allocation = 0.015  # 1.5% initial entry
        self.max_dca_steps = 12
        self.lookback = 60
        
        # State
        self.positions = {}  # {symbol: {avg_price, qty, dca_step}}
        self.market_history = {} # {symbol: [prices]}
        
        # Hyper-Parameters (Stricter than V4)
        self.entry_z_threshold = -3.8  # Extreme outlier
        self.entry_rsi_threshold = 14.0 # Deep exhaustion
        self.min_profit_margin = 0.0025 # 0.25% hard floor
        self.target_roi = 0.028         # 2.8% primary target

    def on_price_update(self, prices):
        action = None
        
        for symbol, price in prices.items():
            if symbol not in self.market_history:
                self.market_history[symbol] = []
            
            hist = self.market_history[symbol]
            hist.append(price)
            
            if len(hist) > self.lookback:
                hist.pop(0)
            
            if len(hist) < self.lookback:
                continue

            # Signal Calculation
            mean = sum(hist) / len(hist)
            variance = sum((x - mean) ** 2 for x in hist) / len(hist)
            stdev = math.sqrt(variance) if variance > 0 else 1e-9
            z_score = (price - mean) / stdev
            
            ups, downs = 0, 0
            for i in range(1, len(hist)):
                diff = hist[i] - hist[i-1]
                if diff > 0: ups += diff
                else: downs += abs(diff)
            rs = ups / (downs if downs > 0 else 1e-9)
            rsi = 100 - (100 / (1 + rs))

            # Logic 1: Position Exit (Strictly Profitable Only)
            if symbol in self.positions:
                pos = self.positions[symbol]
                roi = (price - pos['avg_price']) / pos['avg_price']
                
                # Dynamic Exit: Target reduces as position size increases to speed up capital rotation
                # But never drops below min_profit_margin (Ensuring no STOP_LOSS)
                reduction_factor = (pos['dca_step'] / self.max_dca_steps) * (self.target_roi - self.min_profit_margin)
                current_target = max(self.min_profit_margin, self.target_roi - reduction_factor)
                
                if roi >= current_target:
                    qty = pos['qty']
                    self.balance += (qty * price)
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': ['PROFIT_EXIT_ZSL', f'ROI_{roi:.4f}']
                    }

                # Logic 2: DCA Recovery (Averaging Down)
                if pos['dca_step'] < self.max_dca_steps:
                    # Require a deeper drop for each subsequent step (Logarithmic distancing)
                    drop_distance = (pos['avg_price'] - price) / pos['avg_price']
                    required_drop = 0.02 * math.log(pos['dca_step'] + 2)
                    
                    # Only DCA if price is significantly below average and oversold
                    if drop_distance > required_drop and z_score < -2.0:
                        # Escalating bet size: 1.5x previous step
                        dca_amount = (self.balance * self.base_allocation) * (1.5 ** (pos['dca_step'] + 1))
                        dca_amount = min(dca_amount, self.balance * 0.25) # Max 25% of balance per DCA
                        
                        if self.balance >= dca_amount > 5.0:
                            buy_qty = dca_amount / price
                            new_qty = pos['qty'] + buy_qty
                            new_avg = ((pos['qty'] * pos['avg_price']) + (buy_qty * price)) / new_qty
                            
                            pos['qty'] = new_qty
                            pos['avg_price'] = new_avg
                            pos['dca_step'] += 1
                            self.balance -= dca_amount
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': [f'DCA_STEP_{pos["dca_step"]}', f'DROP_{drop_distance:.4f}']
                            }

            # Logic 3: New Entry (Sniper Protocol)
            else:
                # Enter only on extreme historical anomalies
                if z_score < self.entry_z_threshold and rsi < self.entry_rsi_threshold:
                    entry_amount = self.balance * self.base_allocation
                    if self.balance >= entry_amount > 5.0:
                        qty = entry_amount / price
                        self.positions[symbol] = {
                            'avg_price': price,
                            'qty': qty,
                            'dca_step': 0
                        }
                        self.balance -= entry_amount
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['SNIPER_ENTRY', f'Z_{z_score:.2f}', f'RSI_{rsi:.2f}']
                        }

        return action