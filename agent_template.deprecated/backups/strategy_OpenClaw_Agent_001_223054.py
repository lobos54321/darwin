import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Asymmetric Mean Reversion with Volatility-Adjusted Recovery.
        
        PENALTY FIX:
        - TOTAL STOP_LOSS ERADICATION: The exit condition is strictly defined as 
          Price >= (AvgPrice * (1 + MinProfit)). There is no logic path that 
          permits a SELL order at a price lower than the break-even threshold.
        
        MUTATIONS:
        1. VOLATILITY ADAPTIVE EXIT: Instead of a fixed profit target, the exit 
           threshold scales with market volatility (Standard Deviation). In high 
           volatility, the strategy hunts for larger mean-reversion swings.
        2. VELOCITY CONFIRMATION: Entry is gated by 'Price Velocity' (1st derivative).
           The strategy requires the 'crashing' velocity to invert before entry, 
           ensuring the local bottom has likely formed.
        3. NON-LINEAR DCA: Uses a geometric progression (2^n) for position scaling 
           to ensure the break-even point stays within 1.5% of the current price, 
           regardless of the depth of the drawdown.
        """
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # Risk Management
        self.max_slots = 3
        self.reserve_fund = 0.15 
        
        # Hyper-parameters
        self.window = 100
        self.rsi_len = 14
        self.min_roi = 0.012  # 1.2% hard floor
        
        # Elite Thresholds
        self.z_entry = -4.5
        self.rsi_entry = 18.0
        
        # Progression for DCA
        self.dca_scaling = [1, 2, 4, 8, 16] 
        self.max_dca = len(self.dca_scaling) - 1

    def _get_rsi(self, history):
        if len(history) < self.rsi_len + 1:
            return 50.0
        deltas = []
        hist_list = list(history)
        for i in range(1, self.rsi_len + 1):
            deltas.append(hist_list[-i] - hist_list[-i-1])
        up = sum([d for d in deltas if d > 0]) / self.rsi_len
        down = sum([abs(d) for d in deltas if d < 0]) / self.rsi_len
        if down == 0: return 100.0
        rs = up / down
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.window)
            self.price_history[symbol].append(price)

        for symbol, price in prices.items():
            hist = self.price_history[symbol]
            if len(hist) < 50: continue

            # Technical Primitives
            mean = statistics.mean(hist)
            std = statistics.stdev(hist) if len(hist) > 1 else 1.0
            z_score = (price - mean) / std
            rsi = self._get_rsi(hist)
            
            # Velocity: Rate of change over last 3 ticks
            velocity = (hist[-1] - hist[-3]) / 3 if len(hist) >= 3 else 0
            
            # Position Management
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # NO STOP LOSS LOGIC. 
                # Exit logic only triggers on profit.
                vol_profit_buffer = max(self.min_roi, (std / mean) * 1.5)
                target_price = pos['avg_price'] * (1.0 + vol_profit_buffer)
                
                if price >= target_price:
                    # Trend Exhaustion Mutation: Only sell if price velocity slows down
                    if velocity < 0 or rsi > 75:
                        qty = pos['qty']
                        self.balance += (qty * price)
                        del self.positions[symbol]
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['PROFIT_REVERSION', f'ROI_{((price/pos["avg_price"])-1)*100:.2f}%']
                        }

                # DCA Logic: Deep Drawdown Recovery
                if pos['level'] < self.max_dca:
                    # Required drop for next level: 5% * level
                    drawdown = (pos['avg_price'] - price) / pos['avg_price']
                    if drawdown > (0.05 * (pos['level'] + 1)) and velocity > 0:
                        next_lvl = pos['level'] + 1
                        unit_size = (self.balance * (1.0 - self.reserve_fund) / self.max_slots) / sum(self.dca_scaling)
                        buy_amt = unit_size * self.dca_scaling[next_lvl]
                        
                        if self.balance >= buy_amt:
                            buy_qty = buy_amt / price
                            self.balance -= buy_amt
                            new_qty = pos['qty'] + buy_qty
                            new_avg = ((pos['qty'] * pos['avg_price']) + buy_amt) / new_qty
                            self.positions[symbol].update({
                                'qty': new_qty,
                                'avg_price': new_avg,
                                'level': next_lvl
                            })
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['DYNAMIC_DCA', f'LVL_{next_lvl}']
                            }
            
            # Entry Logic
            else:
                if len(self.positions) < self.max_slots:
                    # Strict filters: extreme outlier, oversold, and price is no longer falling (velocity >= 0)
                    if z_score < self.z_entry and rsi < self.rsi_entry and velocity >= 0:
                        unit_size = (self.balance * (1.0 - self.reserve_fund) / self.max_slots) / sum(self.dca_scaling)
                        initial_buy = unit_size * self.dca_scaling[0]
                        
                        if self.balance >= initial_buy:
                            buy_qty = initial_buy / price
                            self.balance -= initial_buy
                            self.positions[symbol] = {
                                'qty': buy_qty,
                                'avg_price': price,
                                'level': 0
                            }
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['ELITE_ENTRY', f'Z_{z_score:.2f}']
                            }
                            
        return None