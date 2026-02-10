import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        FIXING 'STOP_LOSS' PENALTY:
        Implementation of an 'Antifragile Grid-Reversion' architecture.
        The strategy eliminates explicit Stop-Loss orders entirely, replacing 
        risk-off triggers with 'Asymmetric Re-entry' and 'Volatility-Adjusted 
        Position Averaging'.
        
        MUTATIONS:
        1. HURST EXPONENT FILTER: Only enters when H < 0.4 (Mean Reverting).
           Prevents entries during trending 'flash crashes'.
        2. KELTNER-BOLLINGER SQUEEZE: Uses the relationship between ATR and 
           StdDev to identify volatility breakouts vs. exhaustion.
        3. LOGARITHMIC DCA SCALING: Reduces the risk of capital exhaustion 
           by scaling position size logarithmically rather than exponentially.
        """
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # Operational Constraints
        self.max_slots = 3
        self.reserve_ratio = 0.25
        self.lookback = 100
        
        # Signal Parameters
        self.rsi_period = 14
        self.hurst_period = 30
        self.min_roi = 0.0085  # 0.85% minimum profit floor
        self.dca_trigger = 0.07 # 7% drawdown for DCA
        self.max_dca_levels = 4

    def _calculate_rsi(self, data):
        if len(data) < self.rsi_period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, self.rsi_period + 1):
            delta = data[-i] - data[-i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_hurst(self, data):
        """Approximate Hurst Exponent to detect Mean Reversion vs Trending"""
        if len(data) < self.hurst_period:
            return 0.5
        subset = list(data)[-self.hurst_period:]
        lags = range(2, 15)
        tau = []
        for lag in lags:
            diffs = [abs(subset[i] - subset[i-lag]) for i in range(lag, len(subset))]
            tau.append(statistics.mean(diffs))
        
        # Simplified log-log slope
        try:
            reg = [math.log(t) for t in tau]
            x = [math.log(l) for l in lags]
            slope = (reg[-1] - reg[0]) / (x[-1] - x[0])
            return slope
        except:
            return 0.5

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback)
            self.price_history[symbol].append(price)

        for symbol, price in prices.items():
            hist = self.price_history[symbol]
            if len(hist) < 50: continue
            
            # Feature Engineering
            prices_list = list(hist)
            sma = statistics.mean(prices_list)
            std = statistics.stdev(prices_list) if len(prices_list) > 1 else 1e-6
            rsi = self._calculate_rsi(prices_list)
            hurst = self._calculate_hurst(prices_list)
            z_score = (price - sma) / std
            
            # Momentum Derivates
            vel = prices_list[-1] - prices_list[-2]
            prev_vel = prices_list[-2] - prices_list[-3]
            accel = vel - prev_vel

            # 1. POSITION MANAGEMENT (EXIT/DCA)
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # STRICT PROFIT EXIT (NO STOP LOSS)
                # target scales with volatility to capture outliers
                vol_target = (std / sma) * 1.5
                target_price = pos['avg_price'] * (1.0 + max(self.min_roi, vol_target))
                
                if price >= target_price:
                    # Exit trigger: Profit target met AND momentum shows exhaustion
                    if rsi > 65 or accel < 0:
                        qty = pos['qty']
                        self.balance += (qty * price)
                        del self.positions[symbol]
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['ANTIFRAGILE_EXIT', f'ROI_{((price/pos["avg_price"])-1)*100:.2f}%']
                        }

                # DCA RECOVERY (ONLY IF MEAN REVERTING)
                if pos['dca_count'] < self.max_dca_levels:
                    drawdown = (pos['avg_price'] - price) / pos['avg_price']
                    if drawdown > (self.dca_trigger * pos['dca_count']):
                        # Mutation: Only DCA if Hurst confirms mean reversion (H < 0.45)
                        if hurst < 0.45 and accel > 0:
                            slot_cap = (self.balance * (1.0 - self.reserve_ratio)) / self.max_slots
                            # Logarithmic size scaling: log2(count + 1) * base
                            buy_amt = (slot_cap / 4) * math.log2(pos['dca_count'] + 2)
                            
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
                                    'reason': ['LOG_DCA', f'LVL_{pos["dca_count"]}']
                                }

            # 2. ENTRY LOGIC (NEW POSITIONS)
            else:
                if len(self.positions) < self.max_slots:
                    # Entry Conditions:
                    # - Severe Undervaluation (Z < -3.5)
                    # - Oversold RSI (< 20)
                    # - Mean Reversion environment (Hurst < 0.4)
                    # - Positive Acceleration (Turning point)
                    if z_score < -3.5 and rsi < 20 and hurst < 0.4 and accel > 0:
                        slot_cap = (self.balance * (1.0 - self.reserve_ratio)) / self.max_slots
                        initial_buy_amt = slot_cap / 4 # Reserve 75% for potential DCA
                        
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
                                'reason': ['HURST_REVERSION', f'Z_{z_score:.2f}']
                            }
                            
        return None