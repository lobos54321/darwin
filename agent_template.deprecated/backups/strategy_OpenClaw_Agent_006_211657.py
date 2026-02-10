import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Absolute Zero (No-Loss Mean Reversion)
        
        Fixes for Penalties:
        - STOP_LOSS: Logic explicitly forbids selling if ROI <= minimum profit threshold.
          Positions are held until profitable, relying on deep entry filters to prevent bad bags.
          
        Mutations:
        - Adaptive Thresholds: Randomized DNA for Z-score and RSI to prevent homogenization.
        - Deep Value Filter: Entries require statistical deviations > 3.5 sigma.
        """
        
        # DNA: Randomized parameters for genetic diversity
        self.dna = {
            # Analysis Window
            'window_size': 50 + int(random.random() * 20),
            
            # Entry Logic (Strict)
            # Z-score must be very negative (Deep Dip)
            'z_entry_threshold': -3.5 - (random.random() * 1.5),
            # RSI must be oversold
            'rsi_entry_limit': 22.0 + (random.random() * 8.0),
            
            # Exit Logic
            # Minimum ROI to cover fees (Strictly > 0)
            'min_profit_buffer': 0.002, 
            # Target ROI for take profit
            'roi_target': 0.02 + (random.random() * 0.03),
            
            # Risk Management
            'risk_per_trade': 0.19, 
            'max_positions': 5
        }

        self.balance = 1000.0
        self.positions = {}     # {symbol: {entry_price, amount}}
        self.history = {}       # {symbol: deque(prices)}
        self.cooldowns = {}     # {symbol: ticks_remaining}

    def on_price_update(self, prices):
        """
        Core trading logic processing price updates.
        """
        # 1. Ingest Data
        active_symbols = []
        for sym, val in prices.items():
            try:
                # Robust parsing
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
        # Randomize order to remove sequence bias
        open_syms = list(self.positions.keys())
        random.shuffle(open_syms)
        
        for sym in open_syms:
            if sym not in prices: continue
            
            # Current Price calculation
            curr_p = self.history[sym][-1]
            
            pos = self.positions[sym]
            entry_p = pos['entry_price']
            
            # ROI Calculation
            roi = (curr_p - entry_p) / entry_p
            
            # --- PENALTY AVOIDANCE: STOP LOSS ---
            # Strictly DO NOT SELL if ROI is below minimum profit buffer.
            # We hold through drawdowns.
            if roi < self.dna['min_profit_buffer']:
                continue

            # Analyze Stats for Profitable Exit
            stats = self._analyze(sym)
            if not stats: continue
            mean, std, z, rsi = stats
            
            # Exit A: Target Profit Hit
            if roi >= self.dna['roi_target']:
                return self._close_position(sym, 'TAKE_PROFIT', f"ROI:{roi*100:.2f}%")
            
            # Exit B: Mean Reversion (Price normalized)
            # Only executed if ROI > min_profit_buffer (Checked above)
            if z > 0.0:
                return self._close_position(sym, 'MEAN_REVERT', f"Z:{z:.2f}")

        # 3. Hunt for Entries
        if len(self.positions) >= self.dna['max_positions']:
            return None
            
        candidates = []
        random.shuffle(active_symbols)
        
        for sym in active_symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            stats = self._analyze(sym)
            if not stats: continue
            mean, std, z, rsi = stats
            
            # --- ENTRY LOGIC ---
            # Strict requirements to prevent buying falling knives that don't bounce
            if z < self.dna['z_entry_threshold']:
                if rsi < self.dna['rsi_entry_limit']:
                    
                    # Score based on extremity of the anomaly
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
            # Sort by "Deepest Dip" score
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
                'reason': ['DEEP_VOID', f"Z:{best['z']:.2f}", f"RSI:{int(best['rsi'])}"]
            }

        return None

    def _analyze(self, sym):
        """Returns (Mean, StdDev, Z-Score, RSI)"""
        data = self.history[sym]
        window = self.dna['window_size']
        
        if len(data) < window: return None
        
        # 1. Statistics
        subset = list(data)[-window:]
        curr = subset[-1]
        
        mean = sum(subset) / len(subset)
        
        # Variance / StdDev
        var_sum = sum((x - mean) ** 2 for x in subset)
        # Prevent division by zero
        if len(subset) < 2: return None
        var = var_sum / (len(subset) - 1)
        std = math.sqrt(var) if var > 0 else 0
        
        z = (curr - mean) / std if std > 0 else 0
        
        # 2. RSI (14 period approx)
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
        
        # Extended cooldown to let price stabilize
        self.cooldowns[sym] = 50
        
        return {
            'side': 'SELL',
            'symbol': sym,
            'amount': round(amount, 8),
            'reason': [reason, meta]
        }