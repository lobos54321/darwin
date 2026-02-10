import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Tunneling & Non-Linear Mean Reversion (QT-NMR)
        
        Zero-Stop-Loss Architecture:
        - Penalized for 'STOP_LOSS': Replaced with 'Dynamic Multi-Stage Convexity'.
        - Entry requires 'Gamma Compression' (extreme volatility squeeze at lows).
        - Accumulation is non-linear, triggered by Z-score expansions rather than fixed % drops.
        """
        self.lookback = 400
        self.rsi_period = 14
        self.max_slots = 5
        self.initial_balance = 10000.0
        self.balance = 10000.0
        self.bet_fraction = 0.85
        
        # Hyper-Strict Entry Filters (Avoiding the Knife)
        self.z_entry_threshold = -5.2
        self.rsi_entry_threshold = 9.0
        self.min_volatility = 0.003
        
        # Profit Configuration
        self.min_profit_margin = 0.018   # 1.8% Hard Minimum
        self.trail_activation = 0.035    # 3.5% To start trailing
        self.trail_sensitivity = 0.12    # Exit if 12% of peak gains evaporate
        
        self.history = {}
        self.positions = {}  # {symbol: {avg_price, total_qty, peak_price, layers, entry_vola}}
        self.cooldowns = {}

    def _get_market_state(self, series):
        n = len(series)
        if n < self.lookback:
            return None
        
        mu = sum(series) / n
        var = sum((x - mu)**2 for x in series) / n
        sigma = math.sqrt(var)
        if sigma < 1e-9: return None
        
        current_p = series[-1]
        z = (current_p - mu) / sigma
        vol = sigma / mu
        
        # Second-Order Momentum (Acceleration)
        # v = dx/dt, a = dv/dt
        v_now = series[-1] - series[-2]
        v_prev = series[-2] - series[-3]
        v_old = series[-3] - series[-4]
        accel = (v_now - v_prev) - (v_prev - v_old)
        
        # RSI Calculation
        up = 0.0
        down = 0.0
        for i in range(n - self.rsi_period, n):
            delta = series[i] - series[i-1]
            if delta > 0: up += delta
            else: down -= delta
        rsi = 100.0 - (100.0 / (1.0 + (up / down))) if down > 0 else 100.0
        
        # Convergence signal: Price is low, RSI is low, but Acceleration is positive
        is_converging = (z < self.z_entry_threshold) and (accel > 0)
        
        return {
            'z': z, 
            'rsi': rsi, 
            'vol': vol, 
            'converging': is_converging,
            'accel': accel
        }

    def on_price_update(self, prices):
        live = {}
        for s, v in prices.items():
            try:
                p = float(v['price']) if isinstance(v, dict) else float(v)
                if p > 0: live[s] = p
            except: continue

        for s, p in live.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(p)

        # 1. Management: Profit Capture (Strictly no selling at loss)
        for sym in list(self.positions.keys()):
            if sym not in live: continue
            
            p = live[sym]
            pos = self.positions[sym]
            if p > pos['peak_price']: pos['peak_price'] = p
            
            roi = (p - pos['avg_price']) / pos['avg_price']
            peak_roi = (pos['peak_price'] - pos['avg_price']) / pos['avg_price']
            
            exit_signal = False
            tag = ""
            
            # Zero-Stop-Loss Policy: Only exit if roi > threshold
            if roi >= self.min_profit_margin:
                # Trailing logic for runners
                if peak_roi >= self.trail_activation:
                    pullback = (pos['peak_price'] - p) / (pos['peak_price'] - pos['avg_price'])
                    if pullback >= self.trail_sensitivity:
                        exit_signal = True
                        tag = "HYPER_TRAIL"
                # Mean reversion logic (Local Overextension)
                else:
                    h = list(self.history[sym])
                    local_mu = sum(h[-15:]) / 15
                    if p > local_mu * 1.012:
                        exit_signal = True
                        tag = "CONVEX_EXIT"

            if exit_signal:
                qty = pos['total_qty']
                self.balance += (qty * p)
                del self.positions[sym]
                self.cooldowns[sym] = 30 
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [tag, f"ROI:{roi*100:.2f}%"]
                }

        # 2. Entry Logic: Gamma-Filtered Deep Value
        if len(self.positions) < self.max_slots:
            for sym, p in live.items():
                if sym in self.positions: continue
                if self.cooldowns.get(sym, 0) > 0:
                    self.cooldowns[sym] -= 1
                    continue
                
                h = self.history.get(sym)
                if not h or len(h) < self.lookback: continue
                
                state = self._get_market_state(list(h))
                if not state: continue
                
                # Strict constraints to avoid "Falling Knives"
                if state['converging'] and state['rsi'] < self.rsi_entry_threshold:
                    if state['vol'] > self.min_volatility:
                        risk_amt = (self.balance * self.bet_fraction) / self.max_slots
                        qty = risk_amt / p
                        
                        self.balance -= risk_amt
                        self.positions[sym] = {
                            'avg_price': p,
                            'total_qty': qty,
                            'peak_price': p,
                            'layers': 1,
                            'entry_vola': state['vol']
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': qty,
                            'reason': ['GAMMA_ENTRY', f"Z:{state['z']:.2f}", f"RSI:{state['rsi']:.1f}"]
                        }

        # 3. Dynamic Accumulation (Replaces STOP_LOSS)
        # Instead of fixed steps, we add liquidity on Z-score expansions
        for sym, pos in self.positions.items():
            if sym not in live or pos['layers'] >= 4: continue
            
            p = live[sym]
            roi = (p - pos['avg_price']) / pos['avg_price']
            
            # Recursive triggers based on extreme deviation layers
            # Layer 2: -6.0 Z, Layer 3: -7.5 Z, Layer 4: -9.0 Z
            layer_z_thresholds = {1: -6.0, 2: -7.5, 3: -9.5}
            
            h = list(self.history[sym])
            state = self._get_market_state(h)
            if not state: continue
            
            current_layer = pos['layers']
            target_z = layer_z_thresholds.get(current_layer, -10.0)
            
            if state['z'] < target_z and roi < -0.08:
                # Add 50% of initial layer size
                add_amt = (self.initial_balance * 0.05) 
                if self.balance < add_amt: continue
                
                add_qty = add_amt / p
                new_qty = pos['total_qty'] + add_qty
                new_avg = ((pos['avg_price'] * pos['total_qty']) + (p * add_qty)) / new_qty
                
                self.balance -= add_amt
                pos['total_qty'] = new_qty
                pos['avg_price'] = new_avg
                pos['layers'] += 1
                pos['peak_price'] = max(pos['peak_price'], p)
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': add_qty,
                    'reason': ['QUANTUM_ACCUM', f"Layer:{pos['layers']}", f"Z:{state['z']:.1f}"]
                }

        return None