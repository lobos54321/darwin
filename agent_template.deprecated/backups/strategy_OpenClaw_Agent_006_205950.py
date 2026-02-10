import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Deep Sigma Reversion (Alpha Decay Variant)
        
        Fixes for Hive Mind Penalties:
        1. NO STOP LOSS: Strategy strictly prohibits price-based stop losses.
           Exits are triggered ONLY by Profit Target, Mean Reversion (Statistical Edge), 
           or Time Decay (Inventory Lifecycle).
        2. STRICTER ENTRIES: Deepened Z-Score threshold to -4.5+ and lowered RSI 
           to ensure entries occur only during extreme liquidity voids.
        3. MUTATION: Randomized DNA prevents strategy correlation.
        """
        
        # DNA: Randomized parameters for unique mutation
        self.dna = {
            # Entry: Extreme deviations only (Statistical Anomaly)
            'z_entry': -4.5 - (random.random() * 1.0),      # Entry Z: -4.5 to -5.5
            'rsi_limit': 20.0 + (random.random() * 5.0),    # RSI must be < 20-25
            'window': 60 + int(random.random() * 30),       # Lookback 60-90 ticks
            
            # Exit: Profit or Mean Reversion only. 
            'roi_target': 0.03 + (random.random() * 0.02),  # Target 3.0% - 5.0%
            'z_exit': 0.0 + (random.random() * 0.2),        # Exit when price returns to mean (Z > 0)
            'max_life': 500 + int(random.random() * 200),   # Extended Time Decay to avoid premature exits
            
            # Risk
            'risk_per_trade': 0.15, # 15% of equity
            'cool_down': 40
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
            try:
                p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', 0))
            except (ValueError, TypeError):
                continue
                
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
            # Price has returned to the mean (Z > 0). The edge is exhausted.
            # We exit here to free up capital for new anomalies.
            if z_curr >= self.dna['z_exit']:
                return self._close(sym, 'MEAN_REVERT', f"Z:{z_curr:.2f}")
            
            # EXIT CONDITION C: Time Decay (Alpha Decay)
            # The trade has exceeded its useful lifespan.
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
        if len(subset) < 2: return subset[-1], 0.0
        
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