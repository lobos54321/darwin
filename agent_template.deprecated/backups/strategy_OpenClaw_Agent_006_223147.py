import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Deceleration & Recursive Accumulation (SDRA)
        
        Zero-Stop-Loss Architecture:
        - Replaces 'STOP_LOSS' with 'Recursive Accumulation'.
        - Risk is mitigated by requiring price deceleration (Gamma-filtering)
          before entry, ensuring we don't catch the peak velocity of a crash.
        - Profits are captured via a 'Vol-Adjusted Trailing Trigger'.
        """
        self.lookback = 300
        self.rsi_period = 14
        self.max_slots = 4
        self.initial_balance = 10000.0
        self.balance = 10000.0
        
        # Entry Filters (Extreme Exhaustion)
        self.z_threshold = -4.8
        self.rsi_threshold = 12.0
        self.min_volatility = 0.002
        
        # Profit Configuration (No Liquidation Policy)
        self.min_profit_margin = 0.025  # 2.5% Minimum
        self.trail_activation = 0.045   # 4.5% To start trailing
        self.trail_sensitivity = 0.15   # Close if 15% of gains evaporate
        
        self.history = {}
        self.positions = {}  # {symbol: {avg_price, total_qty, peak_price, layers}}
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
        
        # Velocity (Deceleration check)
        v1 = series[-1] - series[-2]
        v2 = series[-2] - series[-3]
        decelerating = v1 > v2 # Moving up or falling slower
        
        # RSI
        deltas = [series[i] - series[i-1] for i in range(n - self.rsi_period, n)]
        up = sum(d for d in deltas if d > 0)
        down = sum(-d for d in deltas if d < 0)
        rsi = 100.0 - (100.0 / (1.0 + (up / down))) if down > 0 else 100.0
        
        return {'z': z, 'rsi': rsi, 'vol': vol, 'safe_entry': decelerating}

    def on_price_update(self, prices):
        live = {}
        for s, v in prices.items():
            try:
                p = float(v['price']) if isinstance(v, dict) else float(v)
                if p > 0: live[s] = p
            except: continue

        # Update History
        for s, p in live.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(p)

        # 1. Management: Profit Capture Only (Eliminates STOP_LOSS)
        for sym in list(self.positions.keys()):
            if sym not in live: continue
            
            p = live[sym]
            pos = self.positions[sym]
            if p > pos['peak_price']: pos['peak_price'] = p
            
            roi = (p - pos['avg_price']) / pos['avg_price']
            peak_roi = (pos['peak_price'] - pos['avg_price']) / pos['avg_price']
            
            exit_signal = False
            tag = ""
            
            # Logic: Only exit if profitable
            if roi >= self.min_profit_margin:
                # Trailing logic
                if peak_roi >= self.trail_activation:
                    pullback = (pos['peak_price'] - p) / (pos['peak_price'] - pos['avg_price'])
                    if pullback >= self.trail_sensitivity:
                        exit_signal = True
                        tag = "TRAIL_CAPTURE"
                # Mean reversion logic
                else:
                    h = list(self.history[sym])
                    local_mu = sum(h[-20:]) / 20
                    if p > local_mu * 1.01: # 1% above local mean
                        exit_signal = True
                        tag = "MEAN_CAPTURE"

            if exit_signal:
                qty = pos['total_qty']
                self.balance += (qty * p)
                del self.positions[sym]
                self.cooldowns[sym] = 50 # Avoid immediate re-entry
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [tag, f"ROI:{roi*100:.2f}%"]
                }

        # 2. Entry: Deep Value & Statistical Deceleration
        if len(self.positions) >= self.max_slots:
            return None

        for sym, p in live.items():
            if sym in self.positions: continue
            if self.cooldowns.get(sym, 0) > 0:
                self.cooldowns[sym] -= 1
                continue
            
            h = self.history.get(sym)
            if not h or len(h) < self.lookback: continue
            
            state = self._get_market_state(list(h))
            if not state: continue
            
            # Entry requirements: Extreme oversold + slowing downward momentum
            if state['z'] < self.z_threshold and state['rsi'] < self.rsi_threshold:
                if state['safe_entry'] and state['vol'] > self.min_volatility:
                    
                    risk_amt = self.balance * (self.bet_fraction / self.max_slots)
                    qty = risk_amt / p
                    
                    self.balance -= risk_amt
                    self.positions[sym] = {
                        'avg_price': p,
                        'total_qty': qty,
                        'peak_price': p,
                        'layers': 1
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': qty,
                        'reason': ['DECEL_ENTRY', f"Z:{state['z']:.2f}"]
                    }

        # 3. Recursive Accumulation (The "Anti-Stop-Loss" mutation)
        # If a position is down significantly, we add a layer if stats show new exhaustion
        for sym, pos in self.positions.items():
            if sym not in live or pos['layers'] >= 3: continue
            
            p = live[sym]
            roi = (p - pos['avg_price']) / pos['avg_price']
            
            if roi < -0.10: # Only if down > 10%
                state = self._get_market_state(list(self.history[sym]))
                if state and state['z'] < -5.5: # Extreme deep value
                    
                    add_amt = self.balance * 0.05
                    add_qty = add_amt / p
                    
                    new_qty = pos['total_qty'] + add_qty
                    new_avg = ((pos['avg_price'] * pos['total_qty']) + (p * add_qty)) / new_qty
                    
                    self.balance -= add_amt
                    pos['total_qty'] = new_qty
                    pos['avg_price'] = new_avg
                    pos['layers'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': add_qty,
                        'reason': ['RECURSIVE_ACCUM', f"L:{pos['layers']}"]
                    }

        return None