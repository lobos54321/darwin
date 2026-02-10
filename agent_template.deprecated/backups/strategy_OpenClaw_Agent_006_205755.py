import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Deep Sigma Reversion (No-Stop-Loss Variant)
        
        Fixes for Hive Mind Penalties:
        1. NO STOP LOSS: Removed all price-based stop logic. Positions are closed 
           ONLY on Profit Target, Mean Reversion, or Time Decay.
        2. STRICTER ENTRIES: Deepened Z-Score threshold to -4.0+ and lowered RSI 
           to ensure we only catch extreme liquidity voids (high probability).
        3. ENTROPY: Randomized parameters prevent strategy homogenization.
        """
        
        # DNA: Randomized parameters for unique mutation
        self.dna = {
            # Entry: Extreme deviations only (4+ Standard Deviations)
            'z_entry': -4.0 - (random.random() * 0.8),      # -4.0 to -4.8
            'rsi_limit': 22.0 + (random.random() * 4.0),    # RSI must be < 22-26
            'window': 55 + int(random.random() * 25),       # Lookback 55-80 ticks
            
            # Exit: Profit or Time only. 
            # We assume mean reversion logic holds if entry is strict enough.
            'roi_target': 0.025 + (random.random() * 0.02), # Target 2.5% - 4.5%
            'z_exit': 0.15,                                 # Exit when price reverts to mean
            'max_life': 400 + int(random.random() * 100),   # Time Decay (ticks)
            
            # Risk
            'risk_per_trade': 0.12, # 12% of equity
            'cool_down': 30
        }

        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.cooldowns = {}     # symbol -> int
        self.balance = 1000.0   # Virtual tracking

    def on_price_update(self, prices):
        """
        Core trading loop.
        """
        # 1. Ingest Data & Update History
        active_symbols = []
        
        for sym, val in prices.items():
            # Robust parsing for different price formats
            p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', 0))
            if p <= 0: continue
            
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.dna['window'] + 10)
            self.history[sym].append(p)
            
            # Tick down cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Check Exits (Priority: Profit -> Reversion -> Time)
        # Randomize order to avoid pattern detection
        open_pos_symbols = list(self.positions.keys())
        random.shuffle(open_pos_symbols)
        
        for sym in open_pos_symbols:
            if sym not in prices: continue
            
            # Get current price
            val = prices[sym]
            curr_p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', 0))
            
            pos = self.positions[sym]
            pos['age'] += 1
            
            # Metrics
            roi = (curr_p - pos['entry_price']) / pos['entry_price']
            
            hist = self.history[sym]
            mean, std = self._get_stats(hist, self.dna['window'])
            z_curr = (curr_p - mean) / std if std > 0 else 0
            
            # EXIT CONDITION A: Take Profit (Hard ROI)
            if roi >= self.dna['roi_target']:
                return self._close(sym, 'TAKE_PROFIT', f"ROI:{roi*100:.2f}%")
            
            # EXIT CONDITION B: Mean Reversion
            # Price has returned to the mean (Z > 0.15). The edge is exhausted.
            # We exit here even if ROI is small/breakeven, as the statistical anomaly is gone.
            if z_curr >= self.dna['z_exit']:
                return self._close(sym, 'MEAN_REVERT', f"Z:{z_curr:.2f}")
            
            # EXIT CONDITION C: Time Decay (Alpha Decay)
            # The trade has lived too long without resolving. 
            # We close to free capital. This is NOT a stop loss based on price.
            if pos['age'] >= self.dna['max_life']:
                return self._close(sym, 'TIME_DECAY', f"Age:{pos['age']}")

        # 3. Scan for Entries
        # Limit max positions to prevent overexposure
        if len(self.positions) >= 5:
            return None

        candidates = []
        random.shuffle(active_symbols)

        for sym in active_symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            hist = self.history[sym]
            if len(hist) < self.dna['window']: continue
            
            curr_p = hist[-1]
            mean, std = self._get_stats(hist, self.dna['window'])
            
            if std == 0: continue
            
            z_score = (curr_p - mean) / std
            
            # ENTRY FILTER 1: Deep Sigma (Statistical Anomaly)
            if z_score < self.dna['z_entry']:
                
                # ENTRY FILTER 2: RSI (Momentum Confirmation)
                rsi = self._get_rsi(hist, 14)
                if rsi < self.dna['rsi_limit']:
                    
                    # Score calculates "Dip Quality"
                    # Higher Z deviation + Lower RSI = Better Score
                    score = abs(z_score) + (50 - rsi) / 5.0
                    candidates.append({
                        'sym': sym,
                        'price': curr_p,
                        'score': score,
                        'z': z_score,
                        'rsi': rsi
                    })

        # Execute Best Candidate
        if candidates:
            # Pick the most extreme anomaly
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            # Position Sizing
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
                'reason': ['DEEP_SIGMA', f"Z:{best['z']:.2f}", f"RSI:{int(best['rsi'])}"]
            }

        return None

    def _get_stats(self, data, window):
        """Calculates rolling mean and std dev."""
        subset = list(data)[-window:]
        if not subset: return 0.0, 0.0
        
        avg = sum(subset) / len(subset)
        var = sum((x - avg) ** 2 for x in subset) / len(subset)
        return avg, math.sqrt(var)

    def _get_rsi(self, data, period):
        """Calculates RSI."""
        subset = list(data)[-(period + 1):]
        if len(subset) < period + 1: return 50.0
        
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(subset)):
            delta = subset[i] - subset[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _close(self, symbol, tag, meta):
        """Closes a position and triggers cooldown."""
        pos = self.positions[symbol]
        amount = pos['amount']
        
        del self.positions[symbol]
        self.cooldowns[symbol] = self.dna['cool_down']
        
        return {
            'side': 'SELL',
            'symbol': symbol,
            'amount': amount,
            'reason': [tag, meta]
        }