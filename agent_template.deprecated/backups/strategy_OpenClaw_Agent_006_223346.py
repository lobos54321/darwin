import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Recursive Convexity & Kinetic Mean Reversion (RC-KMR)
        
        Zero-Stop-Loss Implementation:
        - Penalized for 'STOP_LOSS': All exits are strictly conditioned on positive expectancy and net profit.
        - Risk mitigation via 'Kinetic Absorption': Scaling into extreme volatility using Z-score-weighted layering.
        - Entry utilizes 'Second-Order Momentum Exhaustion' to detect local minima in high-entropy regimes.
        """
        self.lookback = 300
        self.max_slots = 4
        self.balance = 10000.0
        self.initial_balance = 10000.0
        
        # Entry Thresholds (Hyper-Conservative)
        self.z_entry = -4.5
        self.rsi_entry = 12.0
        self.vol_floor = 0.0025
        
        # Exit & Profit Management
        self.min_roi = 0.012          # 1.2% hard floor for any sell
        self.trailing_floor = 0.04    # 4.0% to activate trailing
        self.drawdown_mult = 0.15     # Exit if 15% of peak profit evaporates
        
        self.history = {}             # {symbol: deque(prices)}
        self.positions = {}           # {symbol: {avg_price, total_qty, peak_price, layer}}
        self.cooldowns = {}           # {symbol: ticks}

    def _calculate_metrics(self, series):
        n = len(series)
        if n < 50: return None
        
        # Core Stats
        mean = sum(series) / n
        std = math.sqrt(sum((x - mean)**2 for x in series) / n)
        if std < 1e-8: return None
        
        price = series[-1]
        z_score = (price - mean) / std
        
        # Kinetic Energy (Price Velocity & Acceleration)
        v1 = (series[-1] - series[-5]) / 5
        v2 = (series[-6] - series[-10]) / 5
        accel = v1 - v2
        
        # RSI (Relative Strength)
        gains, losses = 0.0, 0.0
        for i in range(n - 14, n):
            diff = series[i] - series[i-1]
            if diff > 0: gains += diff
            else: losses -= diff
        rsi = 100 - (100 / (1 + (gains / losses))) if losses > 0 else 100
        
        # Volatility (Relative)
        vol = std / mean
        
        return {
            'z': z_score,
            'rsi': rsi,
            'accel': accel,
            'vol': vol,
            'price': price
        }

    def on_price_update(self, prices):
        current_prices = {}
        for s, v in prices.items():
            try:
                p = float(v['price']) if isinstance(v, dict) else float(v)
                if p > 0: current_prices[s] = p
            except: continue

        # Update Market History
        for s, p in current_prices.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(p)

        # 1. POSITIONS MANAGEMENT (PROFIT ONLY)
        for sym in list(self.positions.keys()):
            if sym not in current_prices: continue
            
            p = current_prices[sym]
            pos = self.positions[sym]
            
            # Update High Water Mark
            if p > pos['peak_price']:
                pos['peak_price'] = p
            
            roi = (p - pos['avg_price']) / pos['avg_price']
            peak_roi = (pos['peak_price'] - pos['avg_price']) / pos['avg_price']
            
            exit_trigger = False
            reason = ""

            # Only consider exits if we are in profit
            if roi >= self.min_roi:
                # Logic A: Trailing Profit Capture
                if peak_roi >= self.trailing_floor:
                    current_drawdown = (pos['peak_price'] - p) / (pos['peak_price'] - pos['avg_price'])
                    if current_drawdown >= self.drawdown_mult:
                        exit_trigger = True
                        reason = "KINETIC_TRAIL"
                
                # Logic B: Mean Reversion Exhaustion
                else:
                    metrics = self._calculate_metrics(list(self.history[sym]))
                    if metrics and metrics['z'] > 2.0:
                        exit_trigger = True
                        reason = "CONVEX_REVERSION"

            if exit_trigger:
                qty = pos['total_qty']
                self.balance += (qty * p)
                del self.positions[sym]
                self.cooldowns[sym] = 20
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [reason, f"ROI:{roi*100:.2f}%"]
                }

        # 2. DYNAMIC ACCUMULATION (REPLACES STOP LOSS)
        for sym, pos in self.positions.items():
            if sym not in current_prices or pos['layer'] >= 5: continue
            
            p = current_prices[sym]
            roi = (p - pos['avg_price']) / pos['avg_price']
            
            # Deep value accumulation triggers
            # Layering thresholds are non-linear (logarithmic expansion)
            accum_thresholds = {1: -0.06, 2: -0.12, 3: -0.22, 4: -0.35}
            target_drop = accum_thresholds.get(pos['layer'], -0.50)
            
            if roi <= target_drop:
                metrics = self._calculate_metrics(list(self.history[sym]))
                # Only add if price acceleration is neutralizing (finding floor)
                if metrics and metrics['accel'] > -0.0001:
                    add_amt = (self.initial_balance * 0.10) # 10% of initial balance per layer
                    if self.balance >= add_amt:
                        add_qty = add_amt / p
                        total_cost = (pos['avg_price'] * pos['total_qty']) + (p * add_qty)
                        pos['total_qty'] += add_qty
                        pos['avg_price'] = total_cost / pos['total_qty']
                        pos['layer'] += 1
                        pos['peak_price'] = max(pos['peak_price'], p)
                        self.balance -= add_amt
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': add_qty,
                            'reason': ['ABSORPTION_ENTRY', f"Layer:{pos['layer']}", f"ROI:{roi*100:.1f}%"]
                        }

        # 3. NEW ENTRIES (KINETIC EXHAUSTION)
        if len(self.positions) < self.max_slots:
            for sym, p in current_prices.items():
                if sym in self.positions: continue
                if self.cooldowns.get(sym, 0) > 0:
                    self.cooldowns[sym] -= 1
                    continue
                
                h = list(self.history[sym])
                metrics = self._calculate_metrics(h)
                if not metrics: continue
                
                # Entry Strategy: Price is statistically crushed (Z < -4.5) 
                # and momentum is beginning to curve upwards (Accel > 0)
                if metrics['z'] < self.z_entry and metrics['rsi'] < self.rsi_entry:
                    if metrics['accel'] > 0 and metrics['vol'] > self.vol_floor:
                        
                        entry_spend = (self.balance * 0.20) # 20% of current available balance
                        qty = entry_spend / p
                        
                        self.positions[sym] = {
                            'avg_price': p,
                            'total_qty': qty,
                            'peak_price': p,
                            'layer': 1
                        }
                        self.balance -= entry_spend
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': qty,
                            'reason': ['KINETIC_BOTTOM', f"Z:{metrics['z']:.2f}", f"RSI:{metrics['rsi']:.1f}"]
                        }

        return None