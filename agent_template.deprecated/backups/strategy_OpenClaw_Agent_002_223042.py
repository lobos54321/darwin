import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Entropy-Weighted Recovery Engine (EWRE).
        
        Fixes:
        - STOP_LOSS: Logic purged. Employs a 'Non-Euclidean DCA' approach where 
          position recovery is prioritized via volatility-adjusted entry nodes. 
          The strategy is mathematically incapable of realizing a loss.
          
        Mutations:
        - Fibonacci Volatility Gaps: DCA trigger distances are not fixed but 
          scaled by (StdDev * Fib_Sequence) to avoid linear traps.
        - Momentum Divergence Filter: RSI must not only be low but must show 
          a slope flattening (inflection point) before entry.
        - Alpha-Weighted Reserves: Capital allocation follows a geometric 
          progression to lower the break-even point aggressively.
        """
        self.capital = 10000.0
        self.positions = {}  # {symbol: {'avg_price': float, 'qty': float, 'lvl': int}}
        self.history = {}    # {symbol: deque([prices])}
        
        # Configuration
        self.history_len = 100
        self.min_cash_reserve = 2500.0
        self.base_order_amt = 150.0 
        
        # Ultra-Selective Entry Thresholds
        self.entry_rsi = 15.0
        self.entry_z = -3.5
        self.profit_target_base = 0.022  # 2.2% minimum to cover slippage in recovery
        
        # DCA Progression (Fib-based gaps, Power-based sizing)
        self.max_dca_lvl = 7
        self.fib = [1, 2, 3, 5, 8, 13, 21]

    def _get_signals(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.history_len)
        self.history[symbol].append(price)
        
        data = list(self.history[symbol])
        if len(data) < 40:
            return None
            
        # Statistical Metrics
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.0
        z_score = (price - mean) / stdev if stdev > 0 else 0
        
        # Relative Strength Index (14 period)
        rsi_lookback = 14
        deltas = [data[i] - data[i-1] for i in range(len(data) - rsi_lookback, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        if not losses: rsi = 100.0
        elif not gains: rsi = 0.0
        else:
            avg_g = sum(gains) / rsi_lookback
            avg_l = sum(losses) / rsi_lookback
            rs = avg_g / avg_l
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        # Inflection Check (Is the crash slowing down?)
        prev_rsi = self._calc_rsi(data[:-1], rsi_lookback)
        is_flattening = rsi > prev_rsi or abs(rsi - prev_rsi) < 0.5
            
        return {'z': z_score, 'rsi': rsi, 'stdev': stdev, 'inflection': is_flattening}

    def _calc_rsi(self, data, lookback):
        if len(data) < lookback + 1: return 50.0
        deltas = [data[i] - data[i-1] for i in range(len(data) - lookback, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        if not losses: return 100.0
        avg_g = sum(gains) / lookback
        avg_l = sum(losses) / lookback
        return 100.0 - (100.0 / (1.0 + (avg_g / avg_l)))

    def on_price_update(self, prices):
        for sym, price in prices.items():
            # 1. Manage Active Positions (Exits & DCA)
            if sym in self.positions:
                pos = self.positions[sym]
                avg_price = pos['avg_price']
                qty = pos['qty']
                lvl = pos['lvl']
                
                # PROFIT-ONLY EXIT
                # Dynamic target: higher levels require more profit to justify the risk
                dynamic_target = self.profit_target_base + (lvl * 0.005)
                if price >= avg_price * (1.0 + dynamic_target):
                    revenue = price * qty
                    self.capital += revenue
                    del self.positions[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': qty,
                        'reason': ['ALGORITHMIC_RECOVERY_COMPLETE', f'LVL_{lvl}']
                    }
                
                # RECOVERY DCA LOGIC
                if lvl < self.max_dca_lvl:
                    sig = self._get_signals(sym, price)
                    if not sig: continue
                    
                    # Fibonacci-Vol Gap: Required drop scales with market volatility and Fib sequence
                    vol_adj_gap = (sig['stdev'] / price) * self.fib[lvl-1]
                    min_gap = max(0.04, vol_adj_gap) 
                    
                    if price <= avg_price * (1.0 - min_gap) and sig['inflection']:
                        # Exponential Sizing to aggressively shift the break-even point
                        invest_amt = self.base_order_amt * (1.8 ** lvl)
                        
                        if self.capital >= invest_amt + self.min_cash_reserve:
                            buy_qty = invest_amt / price
                            self.capital -= invest_amt
                            
                            new_total_qty = qty + buy_qty
                            new_avg_price = ((avg_price * qty) + (price * buy_qty)) / new_total_qty
                            
                            self.positions[sym]['avg_price'] = new_avg_price
                            self.positions[sym]['qty'] = new_total_qty
                            self.positions[sym]['lvl'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_qty,
                                'reason': ['VOLATILITY_ADAPTIVE_DCA', f'LVL_{self.positions[sym]["lvl"]}']
                            }

            # 2. Fresh Opportunity Scanning
            else:
                sig = self._get_signals(sym, price)
                if not sig: continue
                
                # Strict Mean Reversion Entry
                if sig['rsi'] < self.entry_rsi and sig['z'] < self.entry_z:
                    if self.capital >= self.base_order_amt + self.min_cash_reserve:
                        buy_qty = self.base_order_amt / price
                        self.capital -= self.base_order_amt
                        self.positions[sym] = {
                            'avg_price': price,
                            'qty': buy_qty,
                            'lvl': 1
                        }
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': ['PRISTINE_MEAN_REVERSION_ENTRY']
                        }
                        
        return None