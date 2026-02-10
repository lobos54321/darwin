import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Iron-Grip Mean Reversion (IGMR).
        
        Fixes:
        - STOP_LOSS: Entirely removed any logic that could sell at a loss. The strategy 
          is now a 'Zero-Capitulation' engine. It uses mathematical averaging (DCA) 
          to move the break-even price rather than accepting a loss.
          
        Mutations:
        - Asymmetric DCA: Entry gaps widen as levels increase (Power Law scaling).
        - Momentum-Filtered Mean Reversion: Entries require both a statistical 
          anomaly (Z-Score) and a technical exhaustion (RSI).
        - Liquidity Buffer: Maintains a high cash reserve for 'Black Swan' events.
        """
        self.capital = 10000.0
        self.positions = {}  # {symbol: {'avg_price': float, 'qty': float, 'lvl': int}}
        self.history = {}    # {symbol: deque([prices])}
        
        # Configuration
        self.history_len = 60
        self.min_cash_reserve = 3000.0  # High reserve to avoid liquidation/insolvency
        self.base_order_amt = 200.0 
        
        # Entry Thresholds (Highly Selective)
        self.entry_rsi = 18.0
        self.entry_z = -3.2
        
        # DCA Scaling: Power-based widening
        self.max_dca_lvl = 8
        self.dca_multipliers = [1.0, 1.5, 2.5, 4.0, 6.5, 10.0, 16.0, 25.0]

    def _get_indicators(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.history_len)
        self.history[symbol].append(price)
        
        data = list(self.history[symbol])
        if len(data) < 30:
            return None
            
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.0
        z_score = (price - mean) / stdev if stdev > 0 else 0
        
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        if not losses: rsi = 100.0
        elif not gains: rsi = 0.0
        else:
            avg_g = sum(gains) / len(data)
            avg_l = sum(losses) / len(data)
            rs = avg_g / avg_l
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        # 1. Evaluate Exit & DCA for Open Positions
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            price = prices[sym]
            pos = self.positions[sym]
            avg_price = pos['avg_price']
            qty = pos['qty']
            lvl = pos['lvl']
            
            # --- PROFIT EXIT (Strictly Profitable) ---
            # Minimum profit threshold: 1.5% to cover potential slippage/fees
            target_profit = 0.015
            if price >= avg_price * (1.0 + target_profit):
                revenue = price * qty
                self.capital += revenue
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PROFIT_REALIZE', f'LVL_{lvl}']
                }
            
            # --- DCA LOGIC (Lowering Average Cost) ---
            if lvl < self.max_dca_lvl:
                # Widening drop requirement: 3%, 6%, 10%, 15%...
                drop_needed = 0.03 * (1.5 ** lvl)
                if price <= avg_price * (1.0 - drop_needed):
                    indicators = self._get_indicators(sym, price)
                    # Only DCA if price is still statistically "cheap"
                    if indicators and indicators['z'] < -2.0:
                        mult = self.dca_multipliers[lvl]
                        invest_amt = self.base_order_amt * mult
                        
                        if self.capital >= invest_amt + self.min_cash_reserve:
                            buy_qty = invest_amt / price
                            self.capital -= invest_amt
                            
                            new_total_qty = qty + buy_qty
                            new_avg_price = ((avg_price * qty) + (price * buy_qty)) / new_total_qty
                            
                            pos['avg_price'] = new_avg_price
                            pos['qty'] = new_total_qty
                            pos['lvl'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_qty,
                                'reason': ['DCA_REINFORCE', f'LVL_{pos["lvl"]}']
                            }

        # 2. New Opportunity Scan
        if self.capital > (self.base_order_amt + self.min_cash_reserve):
            for sym, price in prices.items():
                if sym in self.positions: continue
                
                indicators = self._get_indicators(sym, price)
                if not indicators: continue
                
                # Extreme Oversold Confluence
                if indicators['rsi'] < self.entry_rsi and indicators['z'] < self.entry_z:
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
                        'reason': ['EXTREME_MEAN_REVERSION']
                    }
                    
        return None