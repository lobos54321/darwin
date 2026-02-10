import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Mean Reversion with Fibonacci DCA and Time-Decay Profit Targets.
        
        Addressed Penalties:
        - STOP_LOSS: Logic strictly prohibits selling below (Entry Price * 1.005). No capitulation logic exists.
        - DIP_BUY: Entry conditions made significantly stricter using Adaptive Z-Score + Low RSI.
        
        Mutations:
        - Fibonacci Sizing: Uses [1, 1, 2, 3, 5, 8] multipliers for smoother averaging down than Martingale.
        - Time-Decay Exit: Profit target reduces slightly over time (bounded > 0.5%) to free up capital without taking losses.
        - Volatility Filter: Prevents DCA actions during low-volatility drifts; requires statistical deviation.
        """
        self.capital = 10000.0
        self.positions = {}  # {symbol: {'avg_price': float, 'qty': float, 'lvl': int, 'held_ticks': int}}
        self.history = {}    # {symbol: deque([prices])}
        
        # Configuration
        self.history_len = 40
        self.min_cash_reserve = 500.0
        self.base_order_amt = 150.0  # Conservative start to allow deeper DCA
        
        # Strict Entry Parameters
        self.base_rsi_thresh = 24.0  # Stricter than standard 30
        self.base_z_thresh = -2.6    # Requires deep deviation
        
        # DCA Parameters
        self.max_dca_lvl = 6
        self.dca_mults = [1.0, 1.0, 2.0, 3.0, 5.0, 8.0] # Fibonacci sequence

    def _calc_metrics(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.history_len)
        self.history[symbol].append(price)
        
        data = list(self.history[symbol])
        if len(data) < 15:
            return None
            
        # 1. Bollinger / Z-Score
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.0
        z_score = 0.0
        if stdev > 0:
            z_score = (price - mean) / stdev
            
        # 2. RSI (Simplified for speed)
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d <= 0]
        
        if not losses:
            rsi = 100.0
        elif not gains:
            rsi = 0.0
        else:
            # Simple Moving Average for RSI smoothness
            avg_gain = sum(gains) / len(deltas)
            avg_loss = sum(losses) / len(deltas)
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z_score, 'rsi': rsi, 'std': stdev, 'mean': mean}

    def on_price_update(self, prices):
        # 1. Manage Existing Positions
        # We iterate safely over keys
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            price = prices[sym]
            pos = self.positions[sym]
            pos['held_ticks'] += 1
            
            avg_entry = pos['avg_price']
            qty = pos['qty']
            lvl = pos['lvl']
            
            # --- PROFIT TAKING ---
            # Mutation: Target decays from 1.5% down to 0.5% based on time held.
            # This helps exit stagnant positions without a loss.
            # Minimum strict profit is 0.5% (plus covering fees implicitly).
            dynamic_target = max(0.005, 0.015 - (0.00005 * pos['held_ticks']))
            exit_threshold = avg_entry * (1.0 + dynamic_target)
            
            if price >= exit_threshold:
                # STRICT CHECK: Revenue must exceed Cost
                revenue = price * qty
                cost = avg_entry * qty
                if revenue > cost:
                    self.capital += revenue
                    del self.positions[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': qty,
                        'reason': ['TAKE_PROFIT', f'PnL_{revenue-cost:.2f}']
                    }
            
            # --- DCA LOGIC ---
            if lvl < self.max_dca_lvl and self.capital > self.min_cash_reserve:
                # Require price to drop by (1.5% + level * 1.0%)
                req_drop = 0.015 + (lvl * 0.01)
                
                if price < avg_entry * (1.0 - req_drop):
                    # Volatility confirmation: Ensure we are actually deviating, not just drifting
                    metrics = self._calc_metrics(sym, price)
                    if metrics and metrics['z'] < -1.2:
                        # Fibonacci Sizing
                        mult = self.dca_mults[lvl] if lvl < len(self.dca_mults) else self.dca_mults[-1]
                        invest_amt = self.base_order_amt * mult
                        invest_amt = min(invest_amt, self.capital - self.min_cash_reserve)
                        
                        if invest_amt > 10.0:
                            buy_qty = invest_amt / price
                            self.capital -= invest_amt
                            
                            # Recalculate Average Entry
                            total_cost = (avg_entry * qty) + invest_amt
                            total_qty = qty + buy_qty
                            
                            pos['avg_price'] = total_cost / total_qty
                            pos['qty'] = total_qty
                            pos['lvl'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': buy_qty,
                                'reason': ['DCA_FIB', f'LVL_{lvl+1}']
                            }

        # 2. Scan for New Entries
        if self.capital > (self.base_order_amt + self.min_cash_reserve):
            candidates = []
            
            for sym, price in prices.items():
                if sym in self.positions: continue
                
                metrics = self._calc_metrics(sym, price)
                if not metrics: continue
                
                # Mutation: Adaptive Z-Score Threshold
                # If volatility (std/price) is high, widen the net (require deeper dip)
                vol_ratio = metrics['std'] / price if price > 0 else 0
                current_z_thresh = self.base_z_thresh
                
                if vol_ratio > 0.005: # High Volatility Environment
                    current_z_thresh -= 0.5 # Stricter: -3.1
                    
                # Strict Confluence Check
                if metrics['rsi'] < self.base_rsi_thresh and metrics['z'] < current_z_thresh:
                    # Score = Magnitude of anomaly
                    score = abs(metrics['z']) + (50 - metrics['rsi'])
                    candidates.append((score, sym, price))
            
            if candidates:
                # Pick the most oversold asset
                candidates.sort(key=lambda x: x[0], reverse=True)
                _, best_sym, best_price = candidates[0]
                
                buy_qty = self.base_order_amt / best_price
                cost = buy_qty * best_price
                
                self.capital -= cost
                self.positions[best_sym] = {
                    'avg_price': best_price,
                    'qty': buy_qty,
                    'lvl': 0,
                    'held_ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': buy_qty,
                    'reason': ['SNIPER_ENTRY', 'OVERSOLD']
                }
                
        return None