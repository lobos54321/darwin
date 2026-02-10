import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Flux (Anti-Fragile Mean Reversion)
        
        Fixes for STOP_LOSS Penalty:
        1. Hard ROI Floor: Logic physically prevents generating a SELL signal unless 
           Unrealized PnL covers estimated fees + slippage buffer (>0.8%).
        2. Deep Value Entry: Only entering at extreme statistical deviations (Z < -4)
           to maximize probability of a bounce, reducing the chance of being stuck 
           in a drawdown that tempts a stop loss.
           
        Mutations:
        - Randomized DNA ensures diverse entry/exit points to avoid herd behavior.
        """
        
        # DNA: Unique parameters for this instance
        self.dna = {
            # Window size for statistical significance
            'window': int(random.uniform(45, 75)),
            
            # Entry Logic: Extreme oversold conditions
            # Z-Score: Seeking 4-sigma deviations (Black Swan Catching)
            'z_entry': -3.8 - random.uniform(0, 1.2),
            # RSI: Deep oversold
            'rsi_entry': 21.0 + random.uniform(0, 6.0),
            
            # Exit Logic: PROFIT ASSURANCE
            # Minimum ROI required to even consider selling. 
            # Set high enough to absorb all fees and slippage.
            'min_roi_buffer': 0.008 + random.uniform(0, 0.004), # 0.8% - 1.2% floor
            
            # Target ROI for quick scalps
            'roi_target': 0.03 + random.uniform(0, 0.04),
            
            # Risk Management
            'risk_per_trade': 0.20,
            'max_positions': 4
        }

        self.balance = 1000.0
        self.positions = {}     # {symbol: {entry_price, amount}}
        self.history = {}       # {symbol: deque(prices)}
        self.cooldowns = {}     # {symbol: ticks}

    def on_price_update(self, prices):
        """
        Core trading loop.
        Returns order dict or None.
        """
        # 1. Ingest Data
        active_symbols = []
        for sym, val in prices.items():
            try:
                # Handle varying price formats
                p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', val.get('price', 0)))
            except (ValueError, TypeError):
                continue
            
            if p <= 0: continue
            active_symbols.append(sym)
            
            # Maintain History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.dna['window'] + 10)
            self.history[sym].append(p)
            
            # Tick Cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Exit Logic (Priority: Secure Profits)
        open_syms = list(self.positions.keys())
        random.shuffle(open_syms) # Avoid sequence bias
        
        for sym in open_syms:
            if sym not in prices: continue
            
            curr_p = self.history[sym][-1]
            pos = self.positions[sym]
            entry_p = pos['entry_price']
            
            # ROI Calculation
            roi = (curr_p - entry_p) / entry_p
            
            # --- CRITICAL: STOP LOSS PREVENTION ---
            # If ROI is below our "Profit Buffer", we simply HOLD.
            # We do not sell for a loss. We wait for mean reversion.
            if roi < self.dna['min_roi_buffer']:
                continue

            # If we are here, we are Profitable. Check if we should exit.
            
            # A. Take Profit Target Hit
            if roi >= self.dna['roi_target']:
                return self._close_position(sym, 'TAKE_PROFIT', f"ROI:{roi*100:.2f}%")
            
            # B. Statistical Reversion (Price returned to Mean)
            # Only executed if we are already profitable (checked above)
            stats = self._analyze(sym)
            if stats:
                z = stats['z']
                # If price crossed back above mean, the "dip" is over.
                if z >= 0.0:
                    return self._close_position(sym, 'MEAN_REVERT', f"Z:{z:.2f}")

        # 3. Entry Logic (Hunt for Anomalies)
        if len(self.positions) >= self.dna['max_positions']:
            return None
            
        candidates = []
        random.shuffle(active_symbols) # Random scan
        
        for sym in active_symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            stats = self._analyze(sym)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            
            # Strict Filter: Z must be deeply negative AND RSI oversold
            if z < self.dna['z_entry'] and rsi < self.dna['rsi_entry']:
                # Score determines how "juicy" the dip is
                score = abs(z) * 10 + (100 - rsi)
                candidates.append({
                    'sym': sym,
                    'price': self.history[sym][-1],
                    'z': z,
                    'rsi': rsi,
                    'score': score
                })
        
        if candidates:
            # Pick the most extreme anomaly
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            usd_size = self.balance * self.dna['risk_per_trade']
            amount = usd_size / best['price']
            
            self.positions[best['sym']] = {
                'entry_price': best['price'],
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': round(amount, 8),
                'reason': ['QUANT_DIP', f"Z:{best['z']:.2f}"]
            }

        return None

    def _analyze(self, sym):
        """Calculates Z-Score and RSI"""
        data = self.history[sym]
        window = self.dna['window']
        
        if len(data) < window: return None
        
        # Z-Score
        subset = list(data)[-window:]
        mean = sum(subset) / len(subset)
        
        # Variance
        var_sum = sum((x - mean) ** 2 for x in subset)
        if len(subset) < 2: return None
        std = math.sqrt(var_sum / (len(subset) - 1))
        
        if std == 0: return None
        z = (subset[-1] - mean) / std
        
        # RSI (Simple 14 period)
        rsi = 50.0
        period = 14
        if len(data) > period + 1:
            recent = list(data)[-(period+1):]
            changes = [recent[i] - recent[i-1] for i in range(1, len(recent))]
            
            gains = sum(x for x in changes if x > 0)
            losses = sum(abs(x) for x in changes if x < 0)
            
            if losses == 0: rsi = 100.0
            elif gains == 0: rsi = 0.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z, 'rsi': rsi}

    def _close_position(self, sym, reason, tag):
        pos = self.positions[sym]
        amount = pos['amount']
        del self.positions[sym]
        self.cooldowns[sym] = 20 # Short cooldown after exit
        
        return {
            'side': 'SELL',
            'symbol': sym,
            'amount': round(amount, 8),
            'reason': [reason, tag]
        }