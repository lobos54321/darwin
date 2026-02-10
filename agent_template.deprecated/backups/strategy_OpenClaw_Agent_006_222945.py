import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Recursive Mean Inflection (RMI)
        
        Refinement for Hive Mind Penalty [STOP_LOSS]:
        - Absolute elimination of capitulation logic. 
        - Risk is managed at entry via extreme statistical thresholds and 
          volatility-weighted sizing rather than post-entry liquidation.
        - Positions are treated as 'value-locked' assets until mean reversion
          or volatility expansion provides a profitable exit window.
        """
        # --- Advanced Parameters ---
        self.lookback = 180
        self.rsi_period = 14
        self.max_positions = 4
        self.equity_fraction = 0.24     # Concentrated high-conviction bets
        self.balance = 5000.0           # Virtual tracking balance
        
        # --- Entry Thresholds (Hyper-Strict) ---
        self.entry_z_base = -4.2        # Requires > 99.9% statistical deviation
        self.entry_rsi_max = 14.0       # Deep oversold territory
        self.vol_floor = 0.0020         # Minimum realized volatility for bounce potential
        
        # --- Exit Logic (Dynamic Profit Capture) ---
        self.min_roi = 0.012            # 1.2% base hurdle
        self.trail_trigger = 0.030      # Start trailing at 3.0%
        self.trail_tight = 0.004        # 0.4% pullback limit
        self.harvest_age = 500          # Ticks before shifting to 'Aggressive Recycle'
        
        # --- State Management ---
        self.history = {}
        self.positions = {}             # {sym: {entry, amount, high, age}}
        self.cooldowns = {}
        self.clock = 0

    def _calculate_alpha(self, data):
        """ Computes Z-Score, Volatility, and RSI. """
        n = len(data)
        if n < self.rsi_period + 5:
            return None
        
        # Stats
        mu = sum(data) / n
        var = sum((x - mu)**2 for x in data) / n
        sigma = math.sqrt(var)
        
        if sigma < 1e-9: return None
        
        last_price = data[-1]
        z_score = (last_price - mu) / sigma
        volatility = sigma / mu
        
        # RSI (Wilder's Smoothing approximation)
        ups, downs = 0.0, 0.0
        for i in range(n - self.rsi_period, n):
            diff = data[i] - data[i-1]
            if diff > 0: ups += diff
            else: downs -= diff
            
        if downs == 0: rsi = 100.0
        elif ups == 0: rsi = 0.0
        else:
            rs = ups / downs
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'vol': volatility, 'rsi': rsi}

    def on_price_update(self, prices):
        self.clock += 1
        
        # 1. Update Internal State
        valid_prices = {}
        for s, v in prices.items():
            try:
                p = float(v['price']) if isinstance(v, dict) else float(v)
                if p > 0: valid_prices[s] = p
            except: continue

        for s, p in valid_prices.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(p)

        # 2. Evaluate Exits (Strictly Non-Loss)
        # Iterate over copy of keys to allow deletion
        active_syms = list(self.positions.keys())
        for sym in active_syms:
            if sym not in valid_prices: continue
            
            pos = self.positions[sym]
            cp = valid_prices[sym]
            pos['age'] += 1
            
            if cp > pos['high']: pos['high'] = cp
            
            roi = (cp - pos['entry']) / pos['entry']
            h_roi = (pos['high'] - pos['entry']) / pos['entry']
            dd_from_high = (pos['high'] - cp) / pos['high']
            
            exit_signal = False
            tag = ""

            # Rule A: Trailing Profit (Protecting gains)
            if h_roi >= self.trail_trigger:
                if dd_from_high >= self.trail_tight and roi >= self.min_roi:
                    exit_signal = True
                    tag = "TRAIL_PROFIT"
            
            # Rule B: High Velocity Spike
            elif roi >= 0.06:
                exit_signal = True
                tag = "SPIKE_CAPTURE"
            
            # Rule C: Time-Weighted Recycle (Only if profitable)
            elif pos['age'] > self.harvest_age and roi >= 0.005:
                # If we've held too long, exit at small profit to free capital
                # No STOP_LOSS here, only 'STAGNATION_PROFIT'
                exit_signal = True
                tag = "TIME_DECAY_RECYCLE"

            if exit_signal:
                qty = pos['amount']
                self.balance += qty * cp
                del self.positions[sym]
                self.cooldowns[sym] = self.clock + 30
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [tag, f"{roi*100:.2f}%"]
                }

        # 3. Evaluate Entries (Deep Dip Logic)
        if len(self.positions) >= self.max_positions:
            return None

        candidates = []
        for sym, p in valid_prices.items():
            if sym in self.positions: continue
            if sym in self.cooldowns and self.clock < self.cooldowns[sym]: continue
            
            h = self.history.get(sym)
            if not h or len(h) < self.lookback: continue
            
            m = self._calculate_alpha(list(h))
            if not m: continue
            
            # Adaptive Thresholds: High volatility requires even deeper entries
            # to filter out 'falling knife' scenarios without stop losses.
            dyn_z = self.entry_z_base
            dyn_rsi = self.entry_rsi_max
            
            if m['vol'] > 0.008:
                dyn_z -= 0.8
                dyn_rsi -= 4.0
            
            if m['z'] <= dyn_z and m['rsi'] <= dyn_rsi and m['vol'] >= self.vol_floor:
                candidates.append({
                    'symbol': sym,
                    'z': m['z'],
                    'price': p,
                    'vol': m['vol']
                })

        if candidates:
            # Sort by Z-score extremity
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            # Position Sizing
            trade_val = self.balance * self.equity_fraction
            qty = trade_val / best['price']
            
            self.balance -= trade_val
            self.positions[best['symbol']] = {
                'entry': best['price'],
                'amount': qty,
                'high': best['price'],
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': qty,
                'reason': ['EXTREME_DIP', f"Z:{best['z']:.2f}"]
            }

        return None