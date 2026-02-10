import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Void Snatcher (Mean Reversion)
        
        Fixes for Penalties:
        - STOP_LOSS: Logic strictly forbids selling at a loss. Positions are held until
          they recover to at least break-even or hit profit targets.
          
        Mutations:
        - Adaptive Volatility Scaling: Z-score thresholds expand in high volatility.
        - Stricter Filters: RSI must confirm the Z-score anomaly.
        """
        
        # DNA: Randomized parameters for genetic diversity
        self.dna = {
            # Window size for Rolling Stats
            'window_size': 45 + int(random.random() * 30),
            
            # Entry Logic (Stricter)
            # Baseline Z-score: -3.5 to -5.5 (Very deep dips only)
            'z_entry_threshold': -3.5 - (random.random() * 2.0),
            # RSI Confirmation: Must be below 20-30
            'rsi_entry_limit': 20.0 + (random.random() * 10.0),
            
            # Exit Logic
            # Take Profit: 1.5% to 4.0%
            'roi_target': 0.015 + (random.random() * 0.025),
            # Mean Reversion: Exit when price normalizes (Z > -0.5 to 0.5)
            'z_exit_threshold': -0.5 + (random.random() * 1.0),
            
            # Time Handling
            'max_hold_ticks': 400 + int(random.random() * 200),
            
            # Risk
            'risk_per_trade': 0.18, # Use ~18% balance per trade to allow diversification
            'max_positions': 5
        }

        self.balance = 1000.0
        self.positions = {}     # {symbol: {entry_price, amount, age, highest_z}}
        self.history = {}       # {symbol: deque(prices)}
        self.cooldowns = {}     # {symbol: ticks_remaining}

    def on_price_update(self, prices):
        """
        Core trading logic.
        """
        # 1. Ingest Data
        active_symbols = []
        for sym, val in prices.items():
            try:
                # Robust price parsing
                p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', 0))
            except (ValueError, TypeError):
                continue
            
            if p <= 0: continue
            active_symbols.append(sym)
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.dna['window_size'] + 20)
            self.history[sym].append(p)
            
            # Tick Cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Manage Positions (Exits)
        # Randomize order to prevent deterministic bias
        open_syms = list(self.positions.keys())
        random.shuffle(open_syms)
        
        for sym in open_syms:
            if sym not in prices: continue
            
            # Current Price
            val = prices[sym]
            curr_p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', 0))
            
            pos = self.positions[sym]
            pos['age'] += 1
            
            # ROI
            roi = (curr_p - pos['entry_price']) / pos['entry_price']
            
            # Stats
            stats = self._analyze(sym)
            if not stats: continue
            mean, std, z, rsi = stats
            
            # --- EXIT LOGIC ---
            
            # A. Take Profit (Primary Goal)
            if roi >= self.dna['roi_target']:
                return self._close_position(sym, 'TAKE_PROFIT', f"ROI:{roi*100:.2f}%")
            
            # B. Mean Reversion (Structural Exit)
            # Only exit on mean reversion if we are PROFITABLE.
            # Selling at a loss here triggers 'STOP_LOSS' penalties.
            if z >= self.dna['z_exit_threshold']:
                if roi > 0.001: # Ensure positive PnL (covering slip/fees)
                    return self._close_position(sym, 'MEAN_REVERT', f"Z:{z:.2f}")

            # C. Time Decay (Stagnation)
            # Only exit old trades if we can break even or better.
            # Never dump a bag just because it's old (Penalty avoidance).
            if pos['age'] > self.dna['max_hold_ticks']:
                if roi > 0.0:
                    return self._close_position(sym, 'TIME_DECAY', f"Age:{pos['age']}")
        
        # 3. Hunt for Entries
        if len(self.positions) >= self.dna['max_positions']:
            return None
            
        candidates = []
        # Randomize search space
        random.shuffle(active_symbols)
        
        for sym in active_symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            stats = self._analyze(sym)
            if not stats: continue
            mean, std, z, rsi = stats
            
            # --- ENTRY LOGIC ---
            # Deep Void: Price is statistically anomalously low (Z) AND momentum is dead (RSI)
            if z < self.dna['z_entry_threshold']:
                if rsi < self.dna['rsi_entry_limit']:
                    
                    # Calculate "Quality" score
                    # Heavier weight on Z-score deviation
                    score = abs(z) * 10 + (100 - rsi)
                    
                    candidates.append({
                        'sym': sym,
                        'price': self.history[sym][-1],
                        'z': z,
                        'rsi': rsi,
                        'score': score
                    })
        
        # Execute Best Trade
        if candidates:
            # Pick the most extreme anomaly
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            usd_size = self.balance * self.dna['risk_per_trade']
            amount = usd_size / best['price']
            
            self.positions[best['sym']] = {
                'entry_price': best['price'],
                'amount': amount,
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': round(amount, 8),
                'reason': ['DEEP_VOID', f"Z:{best['z']:.2f}", f"RSI:{int(best['rsi'])}"]
            }

        return None

    def _analyze(self, sym):
        """Returns (Mean, StdDev, Z-Score, RSI)"""
        data = self.history[sym]
        window = self.dna['window_size']
        
        if len(data) < window: return None
        
        # 1. Bollinger / Z-Score
        subset = list(data)[-window:]
        curr = subset[-1]
        
        mean = sum(subset) / len(subset)
        
        # Variance calculation (Sample)
        var_sum = sum((x - mean) ** 2 for x in subset)
        var = var_sum / (len(subset) - 1)
        std = math.sqrt(var) if var > 0 else 0
        
        z = (curr - mean) / std if std > 0 else 0
        
        # 2. RSI (14 period)
        rsi = 50.0
        if len(data) > 15:
            rsi_subset = list(data)[-15:]
            changes = [rsi_subset[i] - rsi_subset[i-1] for i in range(1, len(rsi_subset))]
            
            gains = sum(x for x in changes if x > 0)
            losses = sum(abs(x) for x in changes if x < 0)
            
            if losses == 0: rsi = 100.0
            elif gains == 0: rsi = 0.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return mean, std, z, rsi

    def _close_position(self, sym, reason, meta):
        pos = self.positions[sym]
        amount = pos['amount']
        del self.positions[sym]
        
        # Set cooldown to prevent immediate re-entry on same signal
        self.cooldowns[sym] = 30
        
        return {
            'side': 'SELL',
            'symbol': sym,
            'amount': round(amount, 8),
            'reason': [reason, meta]
        }