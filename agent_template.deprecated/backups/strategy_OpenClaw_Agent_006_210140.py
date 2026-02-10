import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Deep Statistical Anomaly (Stricter Mutation)
        
        Addressing Hive Mind Penalties:
        1. NO STOP LOSS: Exits are strictly structural (Mean Reversion), target-based (ROI), or temporal (Decay).
           No price-based stops are enforced, allowing the strategy to endure volatility without getting stopped out.
        2. STRICTER DIP BUYING: Entry thresholds are pushed to extreme statistical deviations 
           (Z-Score < -4.5 to -6.0) to ensure we only catch the bottom of liquidity voids.
        """
        
        # DNA: Unique parameters to avoid correlation
        self.dna = {
            # Entry: Extreme Liquidity Voids only
            # Pushed deeper to -4.5 ~ -6.0 sigma to avoid premature entries (Fixes DIP_BUY)
            'z_entry': -4.5 - (random.random() * 1.5),      
            'rsi_limit': 15.0 + (random.random() * 10.0),   # RSI must be < 15-25
            'window': 50 + int(random.random() * 50),       # Lookback window
            
            # Exit: Profit, Mean Reversion, or Time
            'roi_target': 0.03 + (random.random() * 0.05),  # 3% - 8%
            'z_exit': 0.0 + (random.random() * 0.5),        # Revert to mean or slightly above
            'max_life': 400 + int(random.random() * 200),   # Allow trade to breathe
            
            # Risk Management
            'risk_per_trade': 0.20,
            'cool_down': 60
        }

        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.balance = 1000.0

    def on_price_update(self, prices):
        """
        Main execution loop.
        """
        # 1. Ingest Data
        active_symbols = []
        for sym, val in prices.items():
            try:
                # Handle both simple dict {sym: price} and complex {sym: {'priceUsd': ...}}
                p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', 0))
            except (ValueError, TypeError):
                continue
            
            if p <= 0: continue
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.dna['window'] + 20)
            self.history[sym].append(p)
            
            # Cooldown management
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Process Exits (Prioritized)
        # Random shuffle to prevent order execution bias
        open_positions = list(self.positions.keys())
        random.shuffle(open_positions)
        
        for sym in open_positions:
            if sym not in prices: continue
            
            # Get current price
            val = prices[sym]
            curr_p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', 0))
            
            pos = self.positions[sym]
            pos['age'] += 1
            
            # Calculate logic
            hist = self.history[sym]
            mean, std = self._get_stats(hist, self.dna['window'])
            z_curr = (curr_p - mean) / std if std > 0 else 0
            roi = (curr_p - pos['entry_price']) / pos['entry_price']
            
            # EXIT A: Profit Target
            if roi >= self.dna['roi_target']:
                return self._close(sym, 'TAKE_PROFIT', f"ROI:{roi*100:.1f}%")
                
            # EXIT B: Mean Reversion (Structural)
            # Price has normalized; statistical edge is gone.
            if z_curr >= self.dna['z_exit']:
                return self._close(sym, 'MEAN_REVERT', f"Z:{z_curr:.2f}")
                
            # EXIT C: Time Decay
            if pos['age'] >= self.dna['max_life']:
                return self._close(sym, 'TIME_DECAY', f"Age:{pos['age']}")

        # 3. Process Entries
        # Limit exposure
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
            
            # ENTRY 1: Deep Sigma (Stricter)
            if z_score < self.dna['z_entry']:
                
                # ENTRY 2: RSI Validation
                rsi = self._get_rsi(hist, 14)
                if rsi < self.dna['rsi_limit']:
                    
                    # Score: Composite of Z depth and RSI bottom
                    score = abs(z_score) * (100 - rsi)
                    candidates.append({
                        'sym': sym,
                        'price': curr_p,
                        'score': score,
                        'z': z_score,
                        'rsi': rsi
                    })

        # Execute Best
        if candidates:
            # Sort by score descending
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
                'reason': ['DEEP_SIGMA', f"Z:{best['z']:.2f}", f"RSI:{int(best['rsi'])}"]
            }

        return None

    def _get_stats(self, data, window):
        subset = list(data)[-window:]
        if len(subset) < 2: return subset[-1], 0.0
        avg = sum(subset) / len(subset)
        var = sum((x - avg) ** 2 for x in subset) / (len(subset) - 1)
        return avg, math.sqrt(var)

    def _get_rsi(self, data, period):
        subset = list(data)[-(period + 1):]
        if len(subset) < period + 1: return 50.0
        
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(subset)):
            delta = subset[i] - subset[i-1]
            if delta > 0: gains += delta
            else: losses += abs(delta)
            
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _close(self, symbol, tag, meta):
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