import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Asymmetric Volatility Liquidity Absorption (AVLA)
        
        Zero-Stop-Loss Regime:
        - All 'SELL' orders are programmatically locked to (Price > AvgPrice * (1 + Buffer)).
        - Risk is managed via 'Non-Linear Layering' (DCA) to shift the cost-basis during drawdowns.
        - Strategy focuses on 'Statistical Displacement'—entering only when price deviates 5+ sigmas.
        """
        self.lookback = 450
        self.max_slots = 3
        self.balance = 10000.0
        self.initial_balance = 10000.0
        
        # Hyper-Strict Entry Parameters
        self.z_threshold = -5.2       # Extreme statistical outlier
        self.rsi_threshold = 9.0      # Deep oversold
        self.min_volatility = 0.0035  # Ensure we aren't buying dead assets
        
        # Profit Target Logic (No Stop Loss)
        self.min_take_profit = 0.015  # 1.5% Minimum ROI
        self.trailing_kick_in = 0.05  # 5.0% to start trailing
        self.trail_sensitivity = 0.12 # Exit if 12% of gains evaporate
        
        self.history = {}             # {symbol: deque(prices)}
        self.positions = {}           # {symbol: {avg_price, total_qty, peak_price, layer}}
        self.cooldowns = {}           # {symbol: tick_count}

    def _calc_dynamics(self, series):
        n = len(series)
        if n < 100: return None
        
        # Statistical Distribution
        mean = sum(series) / n
        variance = sum((x - mean)**2 for x in series) / n
        std = math.sqrt(variance)
        if std < 1e-9: return None
        
        current_price = series[-1]
        z_score = (current_price - mean) / std
        
        # Relative Strength (14 period)
        gains, losses = 0.0, 0.0
        for i in range(n - 14, n):
            diff = series[i] - series[i-1]
            if diff > 0: gains += diff
            else: losses -= diff
        rsi = 100 - (100 / (1 + (gains / (losses + 1e-9))))
        
        # Fourier-approximated Velocity (Momentum)
        v = (series[-1] - series[-10]) / 10
        prev_v = (series[-11] - series[-20]) / 10
        accel = v - prev_v
        
        return {
            'z': z_score,
            'rsi': rsi,
            'accel': accel,
            'vol': std / mean,
            'p': current_price
        }

    def on_price_update(self, prices):
        raw_prices = {}
        for s, v in prices.items():
            try:
                p = float(v['price']) if isinstance(v, dict) else float(v)
                if p > 0: raw_prices[s] = p
            except: continue

        # Update buffers
        for s, p in raw_prices.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(p)

        # 1. PROFIT CAPTURE (Mandatory Positive ROI)
        for sym in list(self.positions.keys()):
            if sym not in raw_prices: continue
            
            p = raw_prices[sym]
            pos = self.positions[sym]
            roi = (p - pos['avg_price']) / pos['avg_price']
            
            # Record High Water Mark
            if p > pos['peak_price']:
                pos['peak_price'] = p
            
            # Logic: No selling unless ROI > min_take_profit
            if roi >= self.min_take_profit:
                should_sell = False
                tag = ""
                
                # Trailing logic for runners
                peak_roi = (pos['peak_price'] - pos['avg_price']) / pos['avg_price']
                if peak_roi >= self.trailing_kick_in:
                    drawdown_from_peak = (pos['peak_price'] - p) / (pos['peak_price'] - pos['avg_price'])
                    if drawdown_from_peak > self.trail_sensitivity:
                        should_sell = True
                        tag = "AVLA_TRAIL_EXIT"
                
                # Mean Reversion Exhaustion Logic
                else:
                    m = self._calc_dynamics(list(self.history[sym]))
                    if m and m['z'] > 2.5:
                        should_sell = True
                        tag = "AVLA_CONVEX_EXIT"

                if should_sell:
                    amt = pos['total_qty']
                    self.balance += (amt * p)
                    del self.positions[sym]
                    self.cooldowns[sym] = 30 # Post-trade cooldown
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': amt,
                        'reason': [tag, f"ROI_{roi*100:.2f}%"]
                    }

        # 2. STRATEGIC RECOVERY (DCA / LAYER-IN)
        # Replaces STOP_LOSS: Instead of exiting at a loss, we mathematically improve our entry.
        for sym, pos in self.positions.items():
            if sym not in raw_prices or pos['layer'] >= 6: continue
            
            p = raw_prices[sym]
            roi = (p - pos['avg_price']) / pos['avg_price']
            
            # Fibonacci-spaced layering to survive deep crashes
            layer_triggers = [-0.08, -0.15, -0.25, -0.40, -0.60]
            current_trigger = layer_triggers[pos['layer'] - 1]
            
            if roi <= current_trigger:
                m = self._calc_dynamics(list(self.history[sym]))
                # Only layer if the price is showing signs of stabilization (Acceleration > -X)
                if m and m['accel'] > -0.0005:
                    layer_cost = self.initial_balance * 0.12 # 12% allocation for recovery layers
                    if self.balance >= layer_cost:
                        buy_qty = layer_cost / p
                        total_cost = (pos['avg_price'] * pos['total_qty']) + (p * buy_qty)
                        pos['total_qty'] += buy_qty
                        pos['avg_price'] = total_cost / pos['total_qty']
                        pos['layer'] += 1
                        pos['peak_price'] = max(pos['peak_price'], p)
                        self.balance -= layer_cost
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': buy_qty,
                            'reason': ["RECOVERY_LAYER", f"L_{pos['layer']}", f"ROI_{roi*100:.1f}%"]
                        }

        # 3. NEW POSITION ENTRIES (STATISTICAL OUTLIERS)
        if len(self.positions) < self.max_slots:
            for sym, p in raw_prices.items():
                if sym in self.positions: continue
                if self.cooldowns.get(sym, 0) > 0:
                    self.cooldowns[sym] -= 1
                    continue
                
                m = self._calc_dynamics(list(self.history[sym]))
                if not m: continue
                
                # Condition: Price is statistically 'broken' (Z < -5.2) and oversold (RSI < 9)
                # and velocity is turning (Accel > 0)
                if m['z'] < self.z_threshold and m['rsi'] < self.rsi_threshold:
                    if m['accel'] > 0 and m['vol'] > self.min_volatility:
                        
                        # Size entry as 25% of available balance
                        entry_val = self.balance * 0.25
                        qty = entry_val / p
                        
                        self.positions[sym] = {
                            'avg_price': p,
                            'total_qty': qty,
                            'peak_price': p,
                            'layer': 1
                        }
                        self.balance -= entry_val
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': qty,
                            'reason': ["AVLA_ENTRY", f"Z_{m['z']:.2f}", f"RSI_{m['rsi']:.1f}"]
                        }

        return None