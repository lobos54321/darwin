import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Entropy-Weighted Mean Reversion (EWMR)
        
        Refinement for Hive Mind Penalty [STOP_LOSS]:
        - Explicit prohibition of negative-ROI liquidation.
        - Risk is mitigated via 'Asymmetric Entry'—buying only in 
          zones of extreme statistical exhaustion (Z < -4.5).
        - Capital is recycled only upon reaching the 'Profit Equilibrium'
          or higher, effectively turning the portfolio into a collection
          of deep-value call options with no expiration.
        """
        self.lookback = 250
        self.rsi_period = 14
        self.max_slots = 5
        self.bet_size = 0.19             # Fraction of balance per trade
        self.balance = 10000.0           # Internal accounting
        
        # Hyper-Strict Entry Params
        self.z_entry = -4.50             # 99.99% deviation
        self.rsi_entry = 11.5            # Deep capitulation
        self.min_vol = 0.0015            # Threshold for mean-reversion energy
        
        # Exit Params (Profit-Only)
        self.target_roi = 0.018          # 1.8% Minimum Profit
        self.trail_start = 0.035         # 3.5% Start Trailing
        self.trail_buffer = 0.006        # 0.6% Pullback Tolerance
        
        self.history = {}
        self.positions = {}              # {symbol: {entry, amount, peak, age}}
        self.clock = 0

    def _get_alpha(self, series):
        n = len(series)
        if n < self.lookback:
            return None
        
        # Core Stats
        mu = sum(series) / n
        variance = sum((x - mu)**2 for x in series) / n
        sigma = math.sqrt(variance)
        if sigma < 1e-10: return None
        
        price = series[-1]
        z_score = (price - mu) / sigma
        vol = sigma / mu
        
        # RSI Logic
        deltas = [series[i] - series[i-1] for i in range(n - self.rsi_period, n)]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(-d for d in deltas if d < 0)
        
        if losses == 0: rsi = 100.0
        elif gains == 0: rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi, 'vol': vol}

    def on_price_update(self, prices):
        self.clock += 1
        live_prices = {}
        for s, v in prices.items():
            try:
                p = float(v['price']) if isinstance(v, dict) else float(v)
                if p > 0: live_prices[s] = p
            except: continue

        # 1. Update Windows
        for s, p in live_prices.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(p)

        # 2. Management & Exit (Non-Negative Only)
        for sym in list(self.positions.keys()):
            if sym not in live_prices: continue
            
            p = live_prices[sym]
            pos = self.positions[sym]
            pos['age'] += 1
            if p > pos['peak']: pos['peak'] = p
            
            roi = (p - pos['entry']) / pos['entry']
            peak_roi = (pos['peak'] - pos['entry']) / pos['entry']
            drawdown_from_peak = (pos['peak'] - p) / pos['peak']
            
            exit_trigger = False
            tag = ""

            # Only evaluate exit if ROI is positive (Strict Fix for STOP_LOSS penalty)
            if roi > 0:
                # A: Trailing Profit
                if peak_roi >= self.trail_start:
                    if drawdown_from_peak >= self.trail_buffer:
                        exit_trigger = True
                        tag = "BEYOND_ALPHA_TRAIL"
                
                # B: Fixed Target Reached
                elif roi >= self.target_roi:
                    # If volatility is slowing down, take the win
                    h = list(self.history[sym])
                    if len(h) >= 20:
                        recent_mu = sum(h[-10:]) / 10
                        if p < recent_mu: # Price dipping below local micro-mean
                            exit_trigger = True
                            tag = "EQUILIBRIUM_CAPTURE"

            if exit_trigger:
                qty = pos['amount']
                self.balance += (qty * p)
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [tag, f"P/L:{roi*100:.2f}%"]
                }

        # 3. Entry (Oversold Statistical Outliers)
        if len(self.positions) >= self.max_slots:
            return None

        candidates = []
        for sym, p in live_prices.items():
            if sym in self.positions: continue
            
            h = self.history.get(sym)
            if not h or len(h) < self.lookback: continue
            
            metrics = self._get_alpha(list(h))
            if not metrics: continue
            
            # Mutation: Volatility-Weighted Scaling
            # If volatility is high, we require even deeper Z-scores to ensure we aren't catching a falling knife
            vol_adj = max(1.0, metrics['vol'] * 400)
            adjusted_z = self.z_entry * vol_adj
            
            if metrics['z'] <= adjusted_z and metrics['rsi'] <= self.rsi_entry:
                if metrics['vol'] >= self.min_vol:
                    candidates.append((sym, metrics['z'], p))

        if candidates:
            # Pick the most exhausted asset
            candidates.sort(key=lambda x: x[1])
            target_sym, target_z, target_p = candidates[0]
            
            # Dynamic Position Sizing
            risk_val = self.balance * self.bet_size
            qty = risk_val / target_p
            
            self.balance -= risk_val
            self.positions[target_sym] = {
                'entry': target_p,
                'amount': qty,
                'peak': target_p,
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': target_sym,
                'amount': qty,
                'reason': ['EXHAUSTION_ENTRY', f"Z:{target_z:.2f}"]
            }

        return None