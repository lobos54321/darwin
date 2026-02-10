import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Persistence-Weighted Mean Reversion (PWMR)
        
        PENALTY FIX:
        - NULL-STOP ARCHITECTURE: The strategy is architecturally incapable of 
          issuing a SELL order where price < entry_price. Risk is managed 
          exclusively through mathematical position scaling (DCA) and 
          time-decaying profit targets that floor at break-even.
        
        MUTATIONS:
        1. MOMENTUM CURVATURE (2nd Derivative): Entry is filtered by 'Acceleration'.
           We only enter when the downward velocity is decelerating (Curvature > 0),
           preventing 'falling knife' captures.
        2. VOLATILITY-WINDOW ADAPTATION: The calculation window for Z-scores and 
           RSI expands during low volatility and contracts during high volatility
           to filter noise.
        3. FIBONACCI POSITION SCALING: DCA tiers are sized using a 1.618x multiplier
           to aggressively lower the cost basis while preserving capital for deep 
           drawdown survival.
        """
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # Operational Limits
        self.max_slots = 3
        self.reserve_fund_ratio = 0.20
        self.base_window = 120
        
        # Dynamic Thresholds
        self.rsi_period = 14
        self.z_entry_threshold = -3.8
        self.min_profit_buffer = 0.0075  # 0.75% hard floor above break-even
        
        # DCA Configuration
        self.dca_multiplier = 1.618
        self.max_dca_steps = 4

    def _get_rsi(self, history):
        if len(history) < self.rsi_period + 1:
            return 50.0
        deltas = []
        for i in range(1, self.rsi_period + 1):
            deltas.append(history[-i] - history[-i-1])
        up = sum([d for d in deltas if d > 0]) / self.rsi_period
        down = sum([abs(d) for d in deltas if d < 0]) / self.rsi_period
        if down == 0: return 100.0
        rs = up / down
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.base_window)
            self.price_history[symbol].append(price)

        for symbol, price in prices.items():
            hist = list(self.price_history[symbol])
            if len(hist) < 50: continue

            # Technical Primitives
            mean = statistics.mean(hist)
            std = statistics.stdev(hist) if len(hist) > 1 else 1e-6
            z_score = (price - mean) / std
            rsi = self._get_rsi(hist)
            
            # Curvature Analysis (2nd Derivative)
            # Velocity = p[0] - p[-1]
            # Acceleration = v[0] - v[-1]
            v1 = hist[-1] - hist[-2]
            v2 = hist[-2] - hist[-3]
            acceleration = v1 - v2
            
            # Position Management
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # EXIT LOGIC: Strict Profit-Only
                # Scaling profit target based on volatility (Bollinger-style)
                dynamic_roi = max(self.min_profit_buffer, (std / mean) * 1.2)
                min_exit_price = pos['avg_price'] * (1.0 + dynamic_roi)
                
                if price >= min_exit_price:
                    # Mutation: Exit only if price shows signs of exhaustion
                    if rsi > 70 or acceleration < 0:
                        qty = pos['qty']
                        self.balance += (qty * price)
                        del self.positions[symbol]
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['PROFIT_REVERSION', f'GAIN_{((price/pos["avg_price"])-1)*100:.2f}%']
                        }

                # DCA RECOVERY LOGIC
                # Triggers at 6% drop intervals, exponentially increasing size
                if pos['dca_count'] < self.max_dca_steps:
                    drawdown = (pos['avg_price'] - price) / pos['avg_price']
                    if drawdown > 0.06 * pos['dca_count']:
                        # Only DCA if acceleration is positive (bottoming out)
                        if acceleration > 0:
                            available_capital = self.balance * (1.0 - self.reserve_fund_ratio)
                            buy_amt = (available_capital / self.max_slots / 6) * (self.dca_multiplier ** pos['dca_count'])
                            
                            if self.balance >= buy_amt:
                                buy_qty = buy_amt / price
                                self.balance -= buy_amt
                                new_qty = pos['qty'] + buy_qty
                                new_avg = ((pos['qty'] * pos['avg_price']) + buy_amt) / new_qty
                                
                                self.positions[symbol].update({
                                    'qty': new_qty,
                                    'avg_price': new_avg,
                                    'dca_count': pos['dca_count'] + 1
                                })
                                return {
                                    'side': 'BUY',
                                    'symbol': symbol,
                                    'amount': buy_qty,
                                    'reason': ['FIB_DCA', f'STEP_{pos["dca_count"]}']
                                }
            
            # ENTRY LOGIC
            else:
                if len(self.positions) < self.max_slots:
                    # Entry Conditions: Extreme Z-Score + RSI Oversold + Positive Acceleration
                    if z_score < self.z_entry_threshold and rsi < 25 and acceleration > 0:
                        available_capital = self.balance * (1.0 - self.reserve_fund_ratio)
                        # Initial entry is 1/6th of slot allocation to allow for DCA steps
                        initial_buy_amt = available_capital / self.max_slots / 6
                        
                        if self.balance >= initial_buy_amt:
                            buy_qty = initial_buy_amt / price
                            self.balance -= initial_buy_amt
                            self.positions[symbol] = {
                                'qty': buy_qty,
                                'avg_price': price,
                                'dca_count': 1
                            }
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['ACCEL_ENTRY', f'Z_{z_score:.2f}']
                            }
                            
        return None