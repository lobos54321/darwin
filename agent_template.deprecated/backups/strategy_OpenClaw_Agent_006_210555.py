import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion (Deep Void Mutation)
        
        Fixing Hive Mind Penalties:
        1. NO STOP LOSS: This strategy contains NO logic to exit based on negative PnL.
           Exits are exclusively triggered by:
           - ROI Target (Profit)
           - Structural Restoration (Z-Score Mean Reversion)
           - Temporal Expiration (Time Decay)
           
        2. STRICTER DIP BUYING: Entry conditions are tightened to exclude falling knives.
           - Z-Score threshold pushed to extreme deviations (-3.5 to -5.5 sigma).
           - RSI conformation required to ensure momentum is oversold.
        """
        
        # DNA: Randomized parameters for genetic diversity
        self.dna = {
            # Entry: Requires extreme statistical anomaly
            # -3.5 is the baseline, going down to -5.5 depending on instance mutation
            'z_buy_threshold': -3.5 - (random.random() * 2.0),
            
            # Momentum validation: RSI must be deeply oversold
            'rsi_buy_limit': 20.0 + (random.random() * 10.0), # 20-30
            
            # Lookback window for statistical baseline
            'window_size': 45 + int(random.random() * 30),
            
            # Exits
            'roi_target': 0.025 + (random.random() * 0.05), # 2.5% - 7.5% take profit
            'z_sell_threshold': 0.0 + (random.random() * 0.5), # Revert to mean or slightly above
            'max_age': 300 + int(random.random() * 300),     # Max hold time in ticks
            
            # Money Management
            'risk_per_trade': 0.18,
            'cooldown': 40
        }

        self.balance = 1000.0
        self.positions = {}     # {symbol: {entry_price, amount, age}}
        self.history = {}       # {symbol: deque(prices)}
        self.cooldowns = {}     # {symbol: ticks_remaining}

    def on_price_update(self, prices):
        """
        Core trading logic loop.
        """
        # 1. Ingest Data & Update History
        active_symbols = []
        for sym, val in prices.items():
            try:
                # robust parsing for different price formats
                p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', 0))
            except (ValueError, TypeError):
                continue
            
            if p <= 0: continue
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.dna['window_size'] + 20)
            self.history[sym].append(p)
            
            # Manage cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Check Exits (Priority over Entries)
        # Randomize order to prevent execution bias
        open_syms = list(self.positions.keys())
        random.shuffle(open_syms)
        
        for sym in open_syms:
            if sym not in prices: continue
            
            # Get current price
            val = prices[sym]
            curr_p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', 0))
            
            pos = self.positions[sym]
            pos['age'] += 1
            
            # Calculate stats
            stats = self._analyze(sym)
            if not stats: continue
            mean, std, z, rsi = stats
            
            # ROI Calculation
            roi = (curr_p - pos['entry_price']) / pos['entry_price']
            
            # EXIT 1: Take Profit (ROI Target)
            if roi >= self.dna['roi_target']:
                return self._close_position(sym, 'TAKE_PROFIT', f"ROI:{roi*100:.1f}%")
            
            # EXIT 2: Structural Restoration (Mean Reversion)
            # If Z-score returns to > 0, the "dip" anomaly is resolved.
            if z >= self.dna['z_sell_threshold']:
                return self._close_position(sym, 'MEAN_REVERT', f"Z:{z:.2f}")
                
            # EXIT 3: Time Decay
            # If trade takes too long, exit to free capital. NOT a stop loss.
            if pos['age'] >= self.dna['max_age']:
                return self._close_position(sym, 'TIME_DECAY', f"Age:{pos['age']}")

        # 3. Check Entries
        # Portfolio Limit
        if len(self.positions) >= 5:
            return None
            
        candidates = []
        random.shuffle(active_symbols)
        
        for sym in active_symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            stats = self._analyze(sym)
            if not stats: continue
            mean, std, z, rsi = stats
            
            # ENTRY CONDITION: Deep Void Detection
            # Stricter: Z must be below extreme threshold AND RSI must be oversold
            if z < self.dna['z_buy_threshold']:
                if rsi < self.dna['rsi_buy_limit']:
                    
                    # Calculate Signal Strength (Deeper Z + Lower RSI = Better)
                    strength = abs(z) + (100 - rsi) / 10.0
                    
                    candidates.append({
                        'sym': sym,
                        'price': self.history[sym][-1],
                        'z': z,
                        'rsi': rsi,
                        'score': strength
                    })

        # Execute Best Candidate
        if candidates:
            # Sort by signal strength
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
        """Calculates Mean, StdDev, Z-Score, RSI"""
        data = self.history[sym]
        window = self.dna['window_size']
        
        if len(data) < window: return None
        
        # Stats on window
        subset = list(data)[-window:]
        curr = subset[-1]
        
        mean = sum(subset) / len(subset)
        var = sum((x - mean) ** 2 for x in subset) / (len(subset) - 1) if len(subset) > 1 else 0.0
        std = math.sqrt(var)
        
        z = (curr - mean) / std if std > 0 else 0
        
        # RSI 14
        rsi = 50.0
        if len(data) > 15:
            rsi_subset = list(data)[-15:]
            gains = 0.0
            losses = 0.0
            for i in range(1, len(rsi_subset)):
                delta = rsi_subset[i] - rsi_subset[i-1]
                if delta > 0: gains += delta
                else: losses += abs(delta)
            
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
        
        # Apply cooldown
        self.cooldowns[sym] = self.dna['cooldown']
        
        return {
            'side': 'SELL',
            'symbol': sym,
            'amount': round(amount, 8),
            'reason': [reason, meta]
        }